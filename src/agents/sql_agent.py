import os
import urllib.parse

from langchain.chat_models import init_chat_model
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent

from constants import WORKER_MODEL
from state import AgentState

TABLE_ALLOWLIST = [
    "hospitals_master",
    "doctors",
    "primary_specialty",
    "hospital_services",
    "emergencyServices",
    "hospital_metrics",
    "diagnostic_services_complete",
    "insurance_compatibility",
    "patient_journey_templates",
    "doctoravailability",
]

SQL_AGENT_SYSTEM_PROMPT = """You are a read-only SQL analyst for a hospital database.

You may only query these tables:
- hospitals_master: hospital directory (name, city/state/zip, type, bed capacity, trauma level, rating, ownership, accreditation).
- doctors: doctor directory (name, hospital_id, primary_specialty, years_experience, board_certified, languages_spoken, patient_rating, consultation_fee, availability_type).
- primary_specialty: specialty reference (specialty_code, specialty_name, category, common_conditions, typical_procedures, urgency_level).
- hospital_services: services offered per hospital (service_category, service_name, availability_24_7, wait_time_avg_minutes, cost_tier, equipment_level).
- emergencyServices: ER capacity and status per hospital (current_capacity, max_capacity, avg_wait_time, severity_handled, trauma_certification).
- hospital_metrics: performance metrics per hospital (metric_category, metric_name, current_value, benchmark_value, percentile_rank, trend_direction).
- diagnostic_services_complete: diagnostic/imaging tests per hospital (test_category, test_name, cost_estimate, preparation_required, results_timeframe, insurance_accepted).
- insurance_compatibility: insurance plan coverage reference (plan_name, provider_name, hospital_coverage, doctor_coverage, emergency_coverage, diagnostic_coverage, network_type).
- patient_journey_templates: typical care-pathway templates per condition_type (typical_path, decision_points, required_specialists, estimated_timeline).
- doctoravailability: doctor appointment slots (date, time_slot, duration_minutes, appointment_type, is_available, consultation_mode).

Rules:
- When filtering on string columns (e.g. city, state, hospital_name, specialty_name, service_name), always use LOWER(column) LIKE LOWER('%value%') so matching is case-insensitive.
- If a query returns no rows, say plainly that no results were found. Never fabricate an answer or invent data not returned by a query.
- Only use the tables listed above. If a question requires data outside them (e.g. patient records, appointments), say you don't have access to that information.
"""

worker_llm = init_chat_model(WORKER_MODEL, temperature=0)


def _build_read_only_db() -> SQLDatabase:
    user = os.environ["MYSQL_READER_USER"]
    password = urllib.parse.quote_plus(os.environ["MYSQL_READER_PASSWORD"])
    host = os.environ["MYSQL_READER_HOST"]
    port = os.environ["MYSQL_READER_PORT"]
    database = os.environ["MYSQL_READER_DATABASE"]
    uri = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    return SQLDatabase.from_uri(uri, include_tables=TABLE_ALLOWLIST)


_sql_react_agent = create_react_agent(
    model=worker_llm,
    tools=SQLDatabaseToolkit(db=_build_read_only_db(), llm=worker_llm).get_tools(),
    prompt=SQL_AGENT_SYSTEM_PROMPT,
)


def sql_agent(state: AgentState) -> dict:
    recent_messages = state["messages"][-6:]
    result = _sql_react_agent.invoke({"messages": recent_messages})
    answer = result["messages"][-1].content
    return {"sql_result": answer, "messages": [AIMessage(content=answer)]}
