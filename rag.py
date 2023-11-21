import os
import pickle
#api key(추가해서 쓰시오)
from workspace.settings import openai_api_key
from workspace.analogicalPrompt import generateAnalogicalPrompt

from langchain.chat_models import ChatOpenAI
from langchain.retrievers import BM25Retriever, EnsembleRetriever

from langchain.schema.runnable import RunnablePassthrough
from langchain.schema import StrOutputParser

from langchain.retrievers import ParentDocumentRetriever
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.storage import LocalFileStore
from langchain.storage._lc_store import create_kv_docstore

from chromaVectorStore import ChromaVectorStore
from workspace.mdLoader import BaseDBLoader 

###### 시간복잡도 Issue로 HyDE 일단 보류했음. 정확도 측면 제대로 평가하면 쓸 생각.
## embedding config - HyDE
# hyde_prompt_template = """ 
#     Write a passage in Korean to answer the #question in detail.

#     #question : {question}
#     #passage : ...
# """

# hyde_prompt = PromptTemplate(input_variables=["question"], template=hyde_prompt_template)

# hyde_generation_chain = LLMChain(
#     llm=llm, 
#     prompt=hyde_prompt,
# )

# hydeembeddings = HypotheticalDocumentEmbedder(
#     llm_chain=hyde_generation_chain,
#     base_embeddings=embedding,
# )

####################### code 정리하시오

#api key settings
os.environ["OPENAI_API_KEY"] = openai_api_key

class RAGPipeline:
    def __init__(self, model, vectorstore, embedding):
        self.llm = ChatOpenAI(model=model, temperature=0.2)
        self.vectorstore = vectorstore
        self.embedding = embedding
        
        save_path = "workspace/document.pkl"

        if not os.path.exists(save_path) :
            document = BaseDBLoader("workspace/markdownDB").load(is_split=False, is_regex=True)
            ChromaVectorStore.get_pickle(documents=document, save_path=save_path)

        # pickle list 객체 생성 시 로드
        with open('workspace/document.pkl', 'rb') as file:
            self.documents = pickle.load(file)

        child_splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", " ", ""],
            chunk_size=200,
            chunk_overlap=10,
            is_separator_regex=False,
        )

        #### encode cachefile into byte
        fs = LocalFileStore("cache")
        store = create_kv_docstore(fs)

        # ParentDocumentRetriever
        self.parent_retreiver = ParentDocumentRetriever(
            vectorstore=vectorstore,
            docstore=store,
            child_splitter=child_splitter,
            search_type="similarity_score_threshold", 
            search_kwargs={"score_threshold": 0.3,"k":5},
        )

        ## check cachefile exsists 
        if not list(store.yield_keys()) :
            dbloader = BaseDBLoader(path_db="workspace/markdownDB/")
            self.parent_retreiver.add_documents(dbloader.load(is_split=False, is_regex=True))

        # Vector Search Retriever
        # self.chroma_retriever = self.vectorstore.as_retriever(search_type='mmr', search_kwargs={"k":5})

        # BM25 Retriever
        self.bm25_retriever = BM25Retriever.from_documents(documents=self.documents)
        self.bm25_retriever.k = 5

        # Ensemble
        self.ensemble_retriever = EnsembleRetriever(retrievers=[self.bm25_retriever, self.parent_retreiver], weights=[0.5, 0.5])

        # RAG 체인 구성
        self.rag_chain = (
            {"context": self.ensemble_retriever | self.format_docs, "question": RunnablePassthrough()}
            | generateAnalogicalPrompt()
            | self.llm
            | StrOutputParser()
        )

    @staticmethod
    def format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

    def invoke(self, query):
        return self.rag_chain.invoke(query)
    
    def retrieve(self, query):
        return self.parent_retreiver.get_relevant_documents(query)

""" ref
https://python.langchain.com/docs/use_cases/question_answering/vector_db_qa
https://js.langchain.com/docs/modules/chains/popular/vector_db_qa/
https://python.langchain.com/docs/use_cases/question_answering/local_retrieval_qa
"""
# 사용 예:
# pipeline = RAGPipeline()
# result = pipeline.invoke("질문 내용")
