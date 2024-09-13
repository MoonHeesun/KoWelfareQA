import re
import os
import pickle
#api key(추가해서 쓰시오)
from workspace.settings import OPENAI_API_KEY
from workspace.analogicalPrompt import generateAnalogicalPrompt, get_normal_prompt

from langchain_openai import ChatOpenAI
from langchain.retrievers import BM25Retriever, EnsembleRetriever

from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

from langchain.retrievers import ParentDocumentRetriever
from langchain_text_splitters import RecursiveCharacterTextSplitter, SentenceTransformersTokenTextSplitter
from langchain_chroma import Chroma
from langchain.storage import LocalFileStore
from langchain.storage._lc_store import create_kv_docstore

from chromaVectorStore import ChromaVectorStore
from workspace.mdLoader import BaseDBLoader 
from datetime import datetime

from transformers import AutoTokenizer

#api key settings
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

class RAGPipeline:
    def __init__(self, model, vectorstore:Chroma, embedding):
        self.llm = ChatOpenAI(model=model, temperature=0.1, streaming=True)
        self.vectorstore = vectorstore
        self.embedding = embedding
        
        save_path = "workspace/document.pkl"
        if not os.path.exists(save_path) :
            document = BaseDBLoader("workspace/markdownDB").load(is_split=False, is_regex=True)
            ChromaVectorStore.get_pickle(documents=document, save_path=save_path)

        # pickle list 객체 생성 시 로드
        with open('workspace/document.pkl', 'rb') as file:
            self.documents = pickle.load(file)

        child_splitter = SentenceTransformersTokenTextSplitter(
            tokens_per_chunk=128,
            model_name="workspace/model/jhgan_seed_777_lr_1e-5_final",
            # model_name="workspace/model/dadt_epoch2_kha_tok",
            chunk_overlap=10,
        )

        #### encode cachefile into byte(to use ParentDocumentRetriever)
        fs = LocalFileStore("cache")
        store = create_kv_docstore(fs)

        # ParentDocumentRetriever
        self.parent_retreiver = ParentDocumentRetriever(
            vectorstore=vectorstore,
            docstore=store,
            child_splitter=child_splitter,
            search_type="similarity_score_threshold",   
            search_kwargs={"score_threshold":0.5, "k":5},
        )
        ## check cachefile exsists 
        if not list(store.yield_keys()) :
            dbloader = BaseDBLoader(path_db="workspace/markdownDB/")
            self.parent_retreiver.add_documents(dbloader.load(is_split=False, is_regex=True))
            
        # BM25 Retriever
        self.bm25_retriever = BM25Retriever.from_documents(documents=self.documents)
        self.bm25_retriever.k = 1
        # Ensemble
        self.ensemble_retriever = EnsembleRetriever(retrievers=[self.bm25_retriever, self.parent_retreiver], weights=[0.1, 0.9])
        # RAG Chain
        self.rag_chain = (
            {"context": self.ensemble_retriever | self.format_docs, "question": RunnablePassthrough()}
            | get_normal_prompt()
            | self.llm
            | StrOutputParser()
        )

    # $$$ BM25 parsing
    def bm_parse(self, text:str) -> list[str]:
        tokenizer_base = AutoTokenizer.from_pretrained("workspace/model/dadt_epoch2_kha_tok")
        tokenized_list = [tok.replace("##", "") for tok in tokenizer_base.tokenize(text)]
        return tokenized_list

    @staticmethod
    def format_docs(docs):
        ## 어느 제도 부분에서 가져왔는지 나타내는 출처 : medata 활용해서 같이 출력
        sep_str = "\n\n"
        result = []

        for doc in docs:
            ### 이 부분도 수정해야 함.. (key : value로)
            metadata = doc.metadata
            content = doc.page_content 
            content_splitted = content.split('\n\n')

            displayed_text = " ".join(content_splitted[1:])[:300]
            displayed_text = re.sub('\n+', ' ', displayed_text)
            displayed_text += " ..."
            
            
            if metadata.get('url') is not None :
                url = f"""<a href="{metadata['url']}">{metadata['title']}</a>"""
            else :
                url = metadata['title']

            # unsafe_allow_html=True,
            content = f"[{url}]\n\n> 내용 \n\n{displayed_text}"
            formatted_document = content + f"\n\n> 카테고리\n\n {metadata['tag']}"
            #### metadata 붙인거 추가하기.......
            result.append(formatted_document)
        
        return sep_str.join(doc for doc in result)

    def invoke(self, query):
        result = self.rag_chain.invoke(query)
        return result
    
    def retrieve(self, query):
        # query = self.embedding.embed_query(query)
        result = self.ensemble_retriever.get_relevant_documents(query)
        return result
""" ref
https://python.langchain.com/docs/use_cases/question_answering/vector_db_qa
https://js.langchain.com/docs/modules/chains/popular/vector_db_qa/
https://python.langchain.com/docs/use_cases/question_answering/local_retrieval_qa
"""

# 사용 예:
if __name__ == "__main__":
    start_time = datetime.now()

    collection_name = "wf_schema_split"
    persist_directory = "workspace/chroma_storage"

    vectorstore = ChromaVectorStore(**{
        "collection_name":collection_name, 
        "persist_directory":persist_directory,
        "collection_metadata" : {"hnsw:space":"cosine"}
    })

    model = "gpt-3.5-turbo-1106"
    # model = "gpt-4-1106-preview"
    rag_pipeline = RAGPipeline(vectorstore=vectorstore.vs, embedding=vectorstore.emb, model=model)

    retrieval_result = rag_pipeline.retrieve("우울한 청년들에게 지원할 수 있는 서비스")
    print(retrieval_result)
    print(len(retrieval_result))
    end_time = datetime.now()
    print((end_time-start_time).total_seconds(),"seconds.") ### timecheck 11-26:

