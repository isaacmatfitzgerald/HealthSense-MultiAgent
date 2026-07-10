import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
from langchain.chat_models import init_chat_model
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_huggingface import HuggingFaceEmbeddings
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from constants import GRADER_MODEL, WORKER_MODEL
from state import AgentState

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_PERSIST_DIR = os.path.join(_SRC_DIR, "chroma_db")
RAG_CORPUS_DIR = os.path.join(_SRC_DIR, "rag_corpus")
COLLECTION_NAME = "hospital_faq"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
REFINE_MAX = 2

REWRITE_SYSTEM_PROMPT = """You rewrite user questions into effective search queries for a
vector database of hospital FAQ and policy documents (topics like visiting hours, parking,
billing, insurance, departments, patient amenities, discharge process, emergency room
procedures, contact/directions, and appointment booking policy). Respond with ONLY the
rewritten search query, no explanation."""

GRADE_SYSTEM_PROMPT = """You grade whether a retrieved document is relevant to a user's
question. relevant=True only if the document contains information that helps answer the
question; otherwise relevant=False. Be strict — a document about a related but different
topic is not relevant."""

GENERATE_SYSTEM_PROMPT = """You answer hospital FAQ/policy questions using ONLY the provided
context documents. If the answer is not contained in the context, say plainly that you don't
have that information — never fabricate an answer or use outside knowledge."""

CANNOT_ANSWER_MESSAGE = (
    "I don't have information about that in our hospital FAQ documents. "
    "Please contact the hospital directly for details."
)


class DocumentGrade(BaseModel):
    relevant: bool


embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)


def _build_or_load_vectorstore() -> Chroma:
    if os.path.isdir(CHROMA_PERSIST_DIR) and os.listdir(CHROMA_PERSIST_DIR):
        return Chroma(
            persist_directory=CHROMA_PERSIST_DIR,
            embedding_function=embeddings,
            collection_name=COLLECTION_NAME,
        )
    documents = []
    for filename in sorted(os.listdir(RAG_CORPUS_DIR)):
        if not filename.endswith(".txt"):
            continue
        path = os.path.join(RAG_CORPUS_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            documents.append(Document(page_content=f.read(), metadata={"source": filename}))
    return Chroma.from_documents(
        documents,
        embeddings,
        persist_directory=CHROMA_PERSIST_DIR,
        collection_name=COLLECTION_NAME,
    )


vectorstore = _build_or_load_vectorstore()

rewrite_llm = init_chat_model(WORKER_MODEL, temperature=0)
grader_llm = init_chat_model(GRADER_MODEL, temperature=0).with_structured_output(DocumentGrade)
generate_llm = init_chat_model(WORKER_MODEL, temperature=0)


def rewrite_query(state: AgentState) -> dict:
    original_question = state["messages"][-1].content
    previous_query = state["rag_query"]
    if previous_query:
        human_content = (
            f"Original question: {original_question}\n"
            f"Previous search query (did not find relevant results): {previous_query}\n"
            "Write a different search query."
        )
    else:
        human_content = f"Original question: {original_question}"
    response = rewrite_llm.invoke(
        [SystemMessage(content=REWRITE_SYSTEM_PROMPT), HumanMessage(content=human_content)]
    )
    return {"rag_query": response.content, "rephrase_count": state["rephrase_count"] + 1}


def retrieve(state: AgentState) -> dict:
    results = vectorstore.similarity_search(state["rag_query"], k=4)
    return {"documents": results}


def grade_documents(state: AgentState) -> dict:
    documents = state["documents"]
    if not documents:
        return {"documents": [], "proceed_to_generate": False}
    question = state["messages"][-1].content
    grading_inputs = [
        [
            SystemMessage(content=GRADE_SYSTEM_PROMPT),
            HumanMessage(content=f"Question: {question}\n\nDocument:\n{doc.page_content}"),
        ]
        for doc in documents
    ]
    grades = grader_llm.batch(grading_inputs)
    relevant_documents = [doc for doc, grade in zip(documents, grades) if grade.relevant]
    return {
        "documents": relevant_documents,
        "proceed_to_generate": bool(relevant_documents),
    }


def generate(state: AgentState) -> dict:
    context = "\n\n".join(doc.page_content for doc in state["documents"])
    question = state["messages"][-1].content
    response = generate_llm.invoke(
        [
            SystemMessage(content=GENERATE_SYSTEM_PROMPT),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}"),
        ]
    )
    return {"messages": [AIMessage(content=response.content)]}


def cannot_answer(state: AgentState) -> dict:
    return {"messages": [AIMessage(content=CANNOT_ANSWER_MESSAGE)]}


def route_after_grade(state: AgentState) -> str:
    if state["proceed_to_generate"]:
        return "generate"
    if state["rephrase_count"] < REFINE_MAX:
        return "rewrite_query"
    return "cannot_answer"


rag_graph_builder = StateGraph(AgentState)
rag_graph_builder.add_node("rewrite_query", rewrite_query)
rag_graph_builder.add_node("retrieve", retrieve)
rag_graph_builder.add_node("grade_documents", grade_documents)
rag_graph_builder.add_node("generate", generate)
rag_graph_builder.add_node("cannot_answer", cannot_answer)

rag_graph_builder.add_edge(START, "rewrite_query")
rag_graph_builder.add_edge("rewrite_query", "retrieve")
rag_graph_builder.add_edge("retrieve", "grade_documents")
rag_graph_builder.add_conditional_edges(
    "grade_documents",
    route_after_grade,
    {
        "generate": "generate",
        "rewrite_query": "rewrite_query",
        "cannot_answer": "cannot_answer",
    },
)
rag_graph_builder.add_edge("generate", END)
rag_graph_builder.add_edge("cannot_answer", END)

rag_agent = rag_graph_builder.compile()
