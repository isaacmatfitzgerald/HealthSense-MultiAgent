import re

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from constants import WORKER_MODEL
from state import AgentState

from .db import claim_slot_and_book, discover_doctors, fetch_doctor_and_slot, list_available_slots

MAX_COLLECT_ATTEMPTS = 6
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

COLLECTIBLE_FIELDS = (
    "city", "state", "specialty", "doctor_id", "slot_id",
    "patient_name", "patient_email", "patient_phone",
    "appointment_type", "consultation_mode",
)

COLLECT_SYSTEM_PROMPT = """You are collecting information to book a hospital appointment, in three stages:

Stage 1 (discovery): if no doctor has been chosen yet, you need the patient's desired city, state, and
medical specialty. Once known, candidate doctors are looked up automatically and shown to the patient in
the next message — the patient will pick one by doctor_id.

Stage 2 (slot selection): once a doctor is chosen, you need a specific slot_id. Available slots for that
doctor are looked up automatically and shown to the patient — they'll pick one by slot_id.

Stage 3 (patient details): once a doctor and slot are chosen, you need the patient's full name and email
(phone is optional).

Extract every field you can confidently determine from the conversation and from the fields already known
(given below). Only fill in doctor_id or slot_id if the patient clearly referenced one that was actually
shown to them — never guess one. List every field still needed in missing_fields, using exactly these
names: "city", "state", "specialty", "doctor_id", "slot_id", "patient_name", "patient_email".

Always use 2-letter US state abbreviations for the state field (e.g. CA not California, OH not Ohio,
TX not Texas).

For the specialty field, use the medical specialty name not the doctor type — use Cardiology not 
cardiologist, Neurology not neurologist, Oncology not oncologist."""


class BookingExtraction(BaseModel):
    city: str = ""
    state: str = ""
    specialty: str = ""
    doctor_id: str = ""
    slot_id: str = ""
    patient_name: str = ""
    patient_email: str = ""
    patient_phone: str = ""
    appointment_type: str = ""
    consultation_mode: str = ""
    missing_fields: list[str] = Field(default_factory=list)


collect_llm = init_chat_model(WORKER_MODEL, temperature=0).with_structured_output(BookingExtraction)


def collect(state: AgentState) -> dict:
    booking = state.get('booking', {})
    recent_messages = state["messages"][-6:]
    known_fields = {k: v for k, v in booking.items() if k in COLLECTIBLE_FIELDS}
    context = (
        f"Fields already known: {known_fields}\n"
        f"Candidate doctors shown to patient: {booking.get('candidate_doctors', [])}\n"
        f"Candidate slots shown to patient: {booking.get('candidate_slots', [])}"
    )
    extraction = collect_llm.invoke(
        [SystemMessage(content=COLLECT_SYSTEM_PROMPT), *recent_messages, HumanMessage(content=context)]
    )
    updated = dict(booking)
    for field in COLLECTIBLE_FIELDS:
        value = getattr(extraction, field)
        if value:
            updated[field] = value
    updated["missing_fields"] = extraction.missing_fields
    updated["collect_attempts"] = booking.get("collect_attempts", 0) + 1
    return {"booking": updated}


def discover(state: AgentState) -> dict:
    booking = dict(state.get("booking", {}))
    if not booking.get("doctor_id") and booking.get("city") and booking.get("state") and booking.get("specialty"):
        booking["candidate_doctors"] = discover_doctors(booking["city"], booking["state"], booking["specialty"])
    elif booking.get("doctor_id") and not booking.get("slot_id"):
        booking["candidate_slots"] = list_available_slots(booking["doctor_id"])
    return {"booking": booking}


def route_after_collect(state: AgentState) -> str:
    booking = state.get("booking", {})
    if booking.get("collect_attempts", 0) > MAX_COLLECT_ATTEMPTS:
        return "give_up"
    if booking.get("missing_fields"):
        return "ask_for_missing"
    return "guard"


def ask_for_missing(state: AgentState) -> dict:
    booking = state.get("booking", {})
    if not booking.get("doctor_id") and booking.get("city") and booking.get("state") and booking.get("specialty"):
        candidates = booking.get("candidate_doctors")
        if candidates:
            lines = [
                f"- {d['doctor_id']}: Dr. {d['full_name']} ({d['primary_specialty']}) at {d['hospital_name']}, "
                f"{d['city']}, {d['state']} — consultation fee ${d['consultation_fee']}"
                for d in candidates
            ]
            message = (
                "Here are some doctors matching your search:\n" + "\n".join(lines)
                + "\n\nWhich doctor would you like (please give the doctor ID)?"
            )
        else:
            message = (
                f"I couldn't find any doctors matching {booking['specialty']} in "
                f"{booking['city']}, {booking['state']}. Could you try a different city, state, or specialty?"
            )
    elif booking.get("doctor_id") and not booking.get("slot_id"):
        candidates = booking.get("candidate_slots")
        if candidates:
            lines = [
                f"- {s['slot_id']}: {s['date']} at {s['time_slot']} ({s['appointment_type']}, {s['consultation_mode']})"
                for s in candidates
            ]
            message = (
                "Here are the available slots for this doctor:\n" + "\n".join(lines)
                + "\n\nWhich slot would you like (please give the slot ID)?"
            )
        else:
            message = (
                "I couldn't find any available slots for this doctor right now. "
                "Would you like to try a different doctor?"
            )
    else:
        missing = ", ".join(booking.get("missing_fields", []))
        message = f"Could you please provide the following to continue booking your appointment: {missing}?"
    return {"messages": [AIMessage(content=message)]}


def guard(state: AgentState) -> dict:
    booking = dict(state.get("booking", {}))
    doctor_id = booking.get("doctor_id", "")
    slot_id = booking.get("slot_id", "")
    details = fetch_doctor_and_slot(doctor_id, slot_id) if doctor_id and slot_id else None

    if not details:
        booking["doctor_id"] = ""
        booking["slot_id"] = ""
        booking["validated"] = False
        return {"booking": booking}

    if details["is_available"] != 1:
        booking["slot_id"] = ""
        booking["validated"] = False
        return {"booking": booking}

    requested_type = booking.get("appointment_type", "")
    requested_mode = booking.get("consultation_mode", "")
    if requested_type and requested_type != details["appointment_type"]:
        booking["slot_id"] = ""
        booking["validated"] = False
        return {"booking": booking}
    if requested_mode and requested_mode != details["consultation_mode"]:
        booking["slot_id"] = ""
        booking["validated"] = False
        return {"booking": booking}

    if not booking.get("patient_name", "").strip():
        booking["validated"] = False
        return {"booking": booking}

    if not EMAIL_REGEX.match(booking.get("patient_email", "")):
        booking["patient_email"] = ""
        booking["validated"] = False
        return {"booking": booking}

    booking["validated"] = True
    return {"booking": booking}


def route_after_guard(state: AgentState) -> str:
    if state.get("booking", {}).get("validated"):
        return "request_confirmation"
    return "collect"


def request_confirmation(state: AgentState) -> dict:
    booking = state.get("booking", {})
    details = fetch_doctor_and_slot(booking["doctor_id"], booking["slot_id"])
    payload = {
        "doctor_name": details["doctor_name"],
        "date": str(details["date"]),
        "time_slot": str(details["time_slot"]),
        "appointment_type": details["appointment_type"],
        "consultation_mode": details["consultation_mode"],
        "patient_name": booking["patient_name"],
        "patient_email": booking["patient_email"],
        "patient_phone": booking.get("patient_phone", ""),
    }
    confirmed = interrupt(payload)
    return {"booking": {**booking, "confirmed": confirmed}}


def route_after_confirmation(state: AgentState) -> str:
    if state.get("booking", {}).get("confirmed"):
        return "write"
    return "cancelled_response"


def write(state: AgentState) -> dict:
    booking = state.get("booking", {})
    result = claim_slot_and_book(
        booking["slot_id"], booking["patient_name"], booking["patient_email"], booking.get("patient_phone", "")
    )
    return {"booking": {**booking, "write_outcome": result["outcome"]}}


def route_after_write(state: AgentState) -> str:
    if state.get("booking", {}).get("write_outcome") == "success":
        return "confirm_response"
    return "slot_taken_response"


def confirm_response(state: AgentState) -> dict:
    booking = state.get("booking", {})
    details = fetch_doctor_and_slot(booking["doctor_id"], booking["slot_id"])
    message = (
        f"Your appointment with Dr. {details['doctor_name']} on {details['date']} at "
        f"{details['time_slot']} has been confirmed. A confirmation will be sent to "
        f"{booking['patient_email']}."
    )
    return {"messages": [AIMessage(content=message)], "booking": {}}


def slot_taken_response(state: AgentState) -> dict:
    booking = dict(state.get("booking", {}))
    booking["slot_id"] = ""
    booking["candidate_slots"] = []
    booking["write_outcome"] = ""
    message = "Sorry, that slot was just booked by someone else. Let's find you another time."
    return {"messages": [AIMessage(content=message)], "booking": booking}


def give_up(state: AgentState) -> dict:
    message = (
        "I'm having trouble completing this booking. Please try again with clearer details, "
        "or contact the hospital directly to schedule your appointment."
    )
    return {"messages": [AIMessage(content=message)], "booking": {}}


def cancelled_response(state: AgentState) -> dict:
    message = "No problem, I've cancelled that booking request. Let me know if you'd like to try again."
    return {"messages": [AIMessage(content=message)], "booking": {}}


booking_graph_builder = StateGraph(AgentState)
booking_graph_builder.add_node("collect", collect)
booking_graph_builder.add_node("discover", discover)
booking_graph_builder.add_node("ask_for_missing", ask_for_missing)
booking_graph_builder.add_node("guard", guard)
booking_graph_builder.add_node("request_confirmation", request_confirmation)
booking_graph_builder.add_node("write", write)
booking_graph_builder.add_node("confirm_response", confirm_response)
booking_graph_builder.add_node("slot_taken_response", slot_taken_response)
booking_graph_builder.add_node("give_up", give_up)
booking_graph_builder.add_node("cancelled_response", cancelled_response)

booking_graph_builder.add_edge(START, "collect")
booking_graph_builder.add_edge("collect", "discover")
booking_graph_builder.add_conditional_edges(
    "discover",
    route_after_collect,
    {"give_up": "give_up", "ask_for_missing": "ask_for_missing", "guard": "guard"},
)
booking_graph_builder.add_edge("ask_for_missing", END)
booking_graph_builder.add_conditional_edges(
    "guard",
    route_after_guard,
    {"request_confirmation": "request_confirmation", "collect": "collect"},
)
booking_graph_builder.add_conditional_edges(
    "request_confirmation",
    route_after_confirmation,
    {"write": "write", "cancelled_response": "cancelled_response"},
)
booking_graph_builder.add_conditional_edges(
    "write",
    route_after_write,
    {"confirm_response": "confirm_response", "slot_taken_response": "slot_taken_response"},
)
booking_graph_builder.add_edge("confirm_response", END)
booking_graph_builder.add_edge("slot_taken_response", END)
booking_graph_builder.add_edge("give_up", END)
booking_graph_builder.add_edge("cancelled_response", END)

booking_agent = booking_graph_builder.compile()
