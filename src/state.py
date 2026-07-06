from typing import Annotated, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class BookingState(TypedDict, total=False):
    intent_details: str
    candidate_doctors: list[dict]
    doctor_id: str
    slot_id: str
    patient_name: str
    patient_email: str
    patient_phone: str
    missing_fields: list[str]
    validated: bool
    collect_attempts: int


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    intent: str
    sql_result: str
    plot_code: str
    documents: list[Document]
    proceed_to_generate: bool
    rephrase_count: int
    booking: BookingState
