# Hospital Multi-Agent Assistant — Design & Build Plan

This file is the single source of truth for design decisions. Claude Code: read this
before proposing or writing any code. If a task conflicts with this document, stop and
flag the conflict instead of improvising. New feature ideas go to the Parking Lot,
not into the current round.

## 1. Project overview

A LangGraph-based multi-agent assistant over a nationwide US hospital MySQL database.
Users can query hospital/doctor data, see visualizations, ask policy/FAQ questions,
and book appointments with human confirmation. Built as a learning project that must
cover core LangGraph concepts properly — clarity and correctness over cleverness.

Existing codebase: a Streamlit app (`main.py`) with separate LangChain SQL and Python
agents (`llm_agent.py`), keyword-based routing, legacy memory
(`ConversationBufferMemory` + `SQLChatMessageHistory`). Round 1 replaces the routing
and agent orchestration with a LangGraph supervisor graph. Streamlit remains the UI.

## 2. Tech stack and conventions

- Python, LangGraph (v1.x) as orchestration; LangChain components inside nodes.
- Models via `init_chat_model`. Model names live in `constants.py`, never inline.
  - DECIDED (Q1): `anthropic:claude-haiku-4-5`, temperature 0, is the default for
    ALL roles to start. Per-role constants (SUPERVISOR_MODEL, WORKER_MODEL,
    GRADER_MODEL) so any single role can be upgraded to
    `anthropic:claude-sonnet-4-6` later with a one-string change.
  - Escalation policy: if a role underperforms, fix the prompt first; upgrade the
    model second. Most likely upgrade candidates: SQL agent, viz agent.
- No `langchain_classic`, no `AgentExecutor`, no `create_tool_calling_agent`,
  no `ConversationBufferMemory`. Use LangGraph-native patterns.
- Nodes return **partial state updates** (dict of changed fields), never mutated
  full state.
- Structured outputs use Pydantic models with `bool` or `Literal` fields — never
  free-string "Yes"/"No".
- Deterministic logic (validation, slot checks, formatting) is plain Python nodes
  with **no LLM call**.
- Loop-control conditions live in **routers only** — never duplicated inside nodes.
- Every loop has a counter in state and an explicit cap checked by its router.
- LangSmith tracing enabled from day one (env vars only).
- Secrets via Streamlit secrets / env vars. Never hardcode credentials.

## 3. Architecture (Round 1)

Supervisor pattern. One parent graph; booking is a subgraph node.

```
START → supervisor (intent classification, structured output)
  ├─ sql_agent          (read-only DB Q&A)
  ├─ viz_agent          (SQL result → Plotly code)
  ├─ booking_agent      (SUBGRAPH — see 3.2)
  ├─ rag_agent          (hospital FAQ, corrective RAG)
  └─ fallback           (can't classify / unsupported intent)
All terminal nodes → END. Streaming enabled (`stream_mode="updates"` minimum).
```

### 3.1 Intent categories (supervisor structured output)

`data_query` | `visualization` | `booking` | `faq` | `out_of_scope`

Routing guidance: structured facts that live in tables → `data_query`;
policy/procedural prose (visiting rules, preparation instructions, billing
procedures) → `faq`; intent to schedule/cancel/reschedule → `booking`.

### 3.2 Booking subgraph

```
collect (LLM; loop until required fields present — ask user, turn ends, resume)
  → guard (deterministic: doctor exists, slot exists & is_available=1,
           type/mode match, name present, email regex)
  → INTERRUPT (human confirms exact slot + patient details)
  → write (transaction: INSERT appointments + conditional UPDATE
           doctoravailability SET is_available=0 WHERE slot_id=? AND is_available=1;
           check affected rows — 0 rows ⇒ slot stolen ⇒ route to slot_taken response)
  → confirm_response
```

Rules:
- Two-stage funnel: discovery (find doctors by city/state + specialty) then slot
  selection. Round 1 "near me" = city/state equality, NOT geo-distance.
- Denormalized appointment fields (`doctor_id`, `appointment_date`,
  `appointment_time`) are copied **from the slot row**, never from LLM output.
- Cancellation = same agent: `booking_status='Cancelled'` + restore
  `is_available=1`, same transaction discipline.

### 3.3 RAG agent (FAQ)

Corrective RAG, ported from the studied notebook: rewrite → retrieve → grade
(batched) → refine loop (max 2, counter in state) → generate | cannot_answer.
Corpus: 8–15 hand-written hospital FAQ/policy documents (prose only — content that
does NOT fit tables). Vector store: Chroma (`langchain_chroma`).
Embeddings: DECIDED (Q2) — HuggingFace local via `langchain_huggingface`,
`sentence-transformers/all-MiniLM-L6-v2`. No embeddings API keys. Note: if the
embedding model ever changes, the vector store must be rebuilt.

### 3.4 Agent construction details (how each node is built)

**supervisor** — NOT an agent: one LLM call with structured output
(`Literal` intent field + optional brief reasoning). No tools. Input: last user
message + short recent history. Writes `intent`.

**sql_agent** — LangGraph prebuilt `create_react_agent` with
`SQLDatabaseToolkit` tools. The DB connection for this agent uses a READ-ONLY
MySQL user (create `agent_reader` with SELECT-only grants). System prompt
includes: table allowlist (from config, §5), schema summary, LOWER()/LIKE rule
for string comparisons, "No results found" rule (no fabrication). Writes
`sql_result` and a message.

**viz_agent** — NOT an agent: single LLM call. Input: `sql_result`. Output:
Plotly code into `plot_code` (fenced block, no `fig.show()`). It does NOT
execute code. Execution happens in the Streamlit layer (as in the current app),
never inside the graph. If `sql_result` is empty, viz intent routes through
sql_agent first via a fixed edge: supervisor → sql_agent → viz_agent for
`visualization` intent.

**rag_agent** — a SUBGRAPH (like booking): rewrite → retrieve (deterministic)
→ grade (LLM, batched, structured bool) → router → refine loop (max 2) →
generate | cannot_answer. Port of the studied notebook with modern conventions
(§2).

**booking_agent** — subgraph per §3.2. `collect` is an LLM call with structured
output (extracts known fields, lists `missing_fields`); `guard` and `write` are
deterministic Python; `write` uses the READ-WRITE connection — the only place
in the codebase that touches it.

**fallback** — deterministic: fixed template listing capabilities. No LLM.

Connection rule: two MySQL users — `agent_reader` (SELECT only; used by
sql_agent, discovery, availability reads) and `agent_writer` (used ONLY by the
booking write node). Defense in depth on top of §6 rule 1.

## 4. State schema (draft — review before implementing)

```python
class BookingState(TypedDict, total=False):   # per-turn scratch, namespaced
    intent_details: str            # what the user asked for
    candidate_doctors: list[dict]  # discovery results
    doctor_id: str                 # chosen
    slot_id: str                   # chosen
    patient_name: str
    patient_email: str
    patient_phone: str             # optional
    missing_fields: list[str]
    validated: bool
    collect_attempts: int          # loop brake

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]  # PERSISTENT (checkpointer)
    intent: str                    # per-turn; written by supervisor
    sql_result: str                # per-turn; sql_agent → viz_agent
    plot_code: str                 # per-turn; viz_agent output
    documents: list[Document]      # per-turn; rag_agent
    proceed_to_generate: bool      # per-turn; rag grader → router
    rephrase_count: int            # per-turn; rag loop brake
    booking: BookingState          # per-turn scratch
```

Long-term memory (LangGraph **store**, namespace = patient email):
preferences ONLY (preferred doctor, time-of-day, language, saved contact details).
Written only on explicit user request ("remember my details"). NO clinical
information in the store — ever. Store ≠ future patients table (records vs.
preferences).

Per-turn fields are reset at turn start (entry node), mirroring the notebook's
rewriter reset. `messages` is never reset.

## 5. Database contract

Full DDL: see `schema.sql` in repo root (keep in sync with the live DB).

READ-ONLY tables: hospitals_master, doctors, primary_specialty, hospital_services,
emergencyServices, hospital_metrics, diagnostic_services_complete,
insurance_compatibility, patient_journey_templates, doctoravailability (reads).

WRITE surface (Round 1, exhaustive):
- `appointments`: INSERT; UPDATE of `booking_status` only.
- `doctoravailability`: UPDATE of `is_available` only, always conditional
  (`AND is_available = <expected>`).
No other writes. No DDL. No DELETEs.

Identity key (Rounds 1): `patient_email` (indexed). No patients table until Round 2.

## 6. Safety & data rules (non-negotiable)

1. Every DB write goes through: guard → interrupt (human confirm) → transactional,
   race-aware write. No exceptions, including future write agents.
2. Missing verdict ⇒ fail closed (route to the option that does less).
3. No clinical data in the store; preferences only, consent-based.
4. Viz agent receives aggregated data, not patient-identifying rows.
5. RAG generation prompt must instruct: answer only from context; say so if absent.
6. LLM-produced values never overwrite DB-sourced values for existing entities.

## 7. Round plan

### Round 1 — Working multi-agent core  (CURRENT)
Scope: everything in sections 3–6. Streamlit UI updated: streaming updates,
confirm/cancel UI for the interrupt, thread_id per session (checkpointer:
SQLite, `langgraph.checkpoint.sqlite`).
Done when:
- [ ] One conversation can: answer a data question, render a chart, answer an FAQ,
      and complete a booking with confirmation — without restart.
- [ ] Slot race condition demonstrably handled (test: pre-take the slot mid-interrupt).
- [ ] Store round-trip works: "remember my details" → new session pre-fills.
- [ ] Off-topic input routes to fallback gracefully.
- [ ] All conventions in §2 hold (spot-check: no full-state returns, no string verdicts).
- [ ] LangSmith traces visible for a full booking flow.

### Round 2 — Identity and clinical writes
- `patients` table + migration script (backfill from appointments by email;
  dedupe strategy documented).
- Patient registration flow (new write subgraph: validate → interrupt → write).
- Test ordering agent (subgraph, twin of booking; writes require new tables —
  design session first).
- Results viewing (read agent + explicit disclosure-policy decision before build).
- Store and patients table coexist: records in DB, preferences in store.
Done when: register → order test → view result works end-to-end with confirmations;
migration is re-runnable; Round 1 eval conversations still pass.

### Round 3 — Reach and robustness
- Voice: STT in, TTS out, Streamlit layer only — zero graph changes.
- Geo-distance "near me" (haversine, deterministic node) with lat/long index.
- Async conversion (`async def` nodes, `astream`) — mechanical pass.
- Error recovery: retry policies on transient DB/LLM failures; graceful agent-level
  failure → fallback with explanation.
- Evaluation harness: scripted test conversations with expected intents/outcomes;
  run after every change from here on. THE key deliverable of this round.
Done when: eval suite exists and is green; voice demo works; async serving path proven.

### Round 4 — Production posture
- AuthN/AuthZ: login tied to patients table; roles (patient vs. admin —
  viz/metrics agents admin-only).
- Graph behind FastAPI; Streamlit becomes pure frontend (async pays off here).
- Monitoring: LangSmith dashboards; basic rate limiting.
- Dockerized deployment to a small cloud instance.
Done when: a stranger could use it without breaking it or seeing another
patient's data.

## 8. Parking lot (append here; do not build mid-round)

- patients table (→ R2, committed)
- test ordering / results viewing (→ R2, committed)
- voice, geo-distance, async (→ R3, committed)
- multilingual support (doctors.languages_spoken exists; unscheduled)
- hierarchical supervisor teams (only if agent count > ~7; unscheduled)

## 9. Working agreements for Claude Code sessions

- Start in Plan Mode for any task touching >1 file or any DB write path.
- One task per session where possible; reference this file's section numbers.
- Never modify: `schema.sql` (generated), §6 safety rules, write surface (§5)
  without a human-approved design change recorded in this file.
- Prefer small verifiable increments; after each, state how to manually test it.

## 10. Open questions (answer before implementing affected parts)

- Q1: RESOLVED — all-Haiku default, per-role constants, escalate individual roles
  only after prompt fixes fail (see §2).
- Q2: RESOLVED — HuggingFace local embeddings, all-MiniLM-L6-v2 (see §3.3).
- Q3: RESOLVED — Confirm/Cancel buttons in Streamlit for the booking interrupt.
  Button click resumes the graph with a boolean (`Command(resume=...)`). No
  natural-language parsing at write-confirmation boundaries. Rationale:
  transaction boundary ≠ conversation; constrained input at irreversible actions.
  Revisit only in Round 3 for the voice modality.

## 11.Python environment: 

ALWAYS use the project venv. Install with
  ./venv/bin/pip install <pkg>; run with ./venv/bin/python. Never use
  global python/pip. Maintain requirements.txt after any install.
