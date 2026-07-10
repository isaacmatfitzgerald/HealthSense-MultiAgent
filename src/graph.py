import os
import sqlite3
from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agents.booking.booking_agent import booking_agent
from agents.rag_agent import rag_agent
from agents.sql_agent import sql_agent
from agents.viz_agent import viz_agent
from constants import SUPERVISOR_MODEL
from state import AgentState

CHECKPOINT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "graph_checkpoints.sqlite"
)

SUPERVISOR_SYSTEM_PROMPT = """You are the intent router for a hospital assistant.
Classify the user's most recent message into exactly one intent:

- data_query: a question answerable from structured hospital/doctor tables
  (facilities, specialties, services, metrics, insurance, availability).
- visualization: the user wants a chart, plot, or graph of data.
- booking: intent to schedule, reschedule, or cancel an appointment.
- faq: policy or procedural prose (visiting rules, preparation instructions,
  billing procedures) that does not live in a table.
- out_of_scope: anything else, or anything you cannot confidently classify.

Use the short recent conversation history only for context on an ambiguous
follow-up message; classify the latest user message."""

FALLBACK_MESSAGE = (
    "I can help with hospital data questions, visualizations, appointment "
    "booking, and hospital policy/FAQ questions. I couldn't match your "
    "request to one of those — could you rephrase?"
)


class SupervisorDecision(BaseModel):
    intent: Literal["data_query", "visualization", "booking", "faq", "out_of_scope"]
    reasoning: str = Field(default="", description="Brief reasoning for the classification")


supervisor_llm = init_chat_model(SUPERVISOR_MODEL, temperature=0).with_structured_output(
    SupervisorDecision
)


def reset_turn_state(state: AgentState) -> dict:
    return {
        "intent": "",
        "sql_result": "",
        "plot_code": "",
        "rag_query": "",
        "documents": [],
        "proceed_to_generate": False,
        "rephrase_count": 0,
    }


def supervisor(state: AgentState) -> dict:
    recent_messages = state["messages"][-6:]
    decision = supervisor_llm.invoke(
        [SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT), *recent_messages]
    )
    return {"intent": decision.intent}


def fallback(state: AgentState) -> dict:
    return {"messages": [AIMessage(content=FALLBACK_MESSAGE)]}


def stub_not_implemented(state: AgentState) -> dict:
    return {
        "messages": [
            AIMessage(
                content=(
                    f"The '{state['intent']}' capability isn't implemented "
                    "yet in this build."
                )
            )
        ]
    }


def route_after_supervisor(state: AgentState) -> str:
    if state["intent"] == "out_of_scope":
        return "fallback"
    if state["intent"] in ("data_query", "visualization"):
        return "sql_agent"
    if state["intent"] == "faq":
        return "rag_agent"
    if state["intent"] == "booking":
        return "booking_agent"
    return "stub_not_implemented"


def route_after_sql_agent(state: AgentState) -> str:
    if state["intent"] == "visualization":
        return "viz_agent"
    return END



graph_builder = StateGraph(AgentState)
graph_builder.add_node("reset_turn_state", reset_turn_state)
graph_builder.add_node("supervisor", supervisor)
graph_builder.add_node("fallback", fallback)
graph_builder.add_node("stub_not_implemented", stub_not_implemented)
graph_builder.add_node("sql_agent", sql_agent)
graph_builder.add_node("viz_agent", viz_agent)
graph_builder.add_node("rag_agent", rag_agent)
graph_builder.add_node("booking_agent", booking_agent)

graph_builder.add_edge(START, "reset_turn_state")
graph_builder.add_edge("reset_turn_state", "supervisor")
graph_builder.add_conditional_edges(
    "supervisor",
    route_after_supervisor,
    {
        "fallback": "fallback",
        "stub_not_implemented": "stub_not_implemented",
        "sql_agent": "sql_agent",
        "rag_agent": "rag_agent",
        "booking_agent": "booking_agent",
    },
)
graph_builder.add_edge("fallback", END)
graph_builder.add_edge("stub_not_implemented", END)
graph_builder.add_conditional_edges(
    "sql_agent", route_after_sql_agent, {"viz_agent": "viz_agent", END: END}
)
graph_builder.add_edge("viz_agent", END)
graph_builder.add_edge("rag_agent", END)
graph_builder.add_edge("booking_agent", END)


def build_graph():
    conn = sqlite3.connect(CHECKPOINT_DB_PATH, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return graph_builder.compile(checkpointer=checkpointer)
