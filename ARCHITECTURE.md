# FATHOM — Architecture & Team Reference

> **Single source of truth for all team members.**
> Every schema, enum, API contract, and convention is defined here.
> If your code contradicts this document, this document wins. Update it via PR if something needs to change.

**Last Updated:** 2026-08-23
**Maintainer:** Prashlesh (Foundation Lead)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Directory Structure](#3-directory-structure)
4. [Shared Enums & Constants](#4-shared-enums--constants)
5. [Database Schema Contracts](#5-database-schema-contracts)
6. [API Contracts (Pydantic Schemas)](#6-api-contracts-pydantic-schemas)
7. [REST API Endpoints](#7-rest-api-endpoints)
8. [SDK Interface (`@fathom_trace`)](#8-sdk-interface-fathom_trace)
9. [Evaluation Engine Contract](#9-evaluation-engine-contract)
10. [Time-Travel Rewind Contract](#10-time-travel-rewind-contract)
11. [Frontend Data Flow](#11-frontend-data-flow)
12. [Team Ownership Matrix](#12-team-ownership-matrix)
13. [Git Workflow & Branch Strategy](#13-git-workflow--branch-strategy)
14. [Development Setup](#14-development-setup)
15. [Dependency Map & Blocking Order](#15-dependency-map--blocking-order)

---

## 1. Project Overview

**Fathom** is a causal tracing and visual debugging platform for multi-step AI agents.

**Core flow:**
```
Agent executes steps → SDK captures spans as a DAG → FastAPI ingests & stores →
Evaluation engine scores each span → React Flow UI visualizes the causal tree →
Developers edit failing nodes & re-run downstream branches
```

**Tech Stack:**

| Layer              | Technology                                         |
| ------------------ | -------------------------------------------------- |
| SDK                | Python 3.11+, `contextvars`, `httpx` (async)       |
| Backend            | FastAPI, Uvicorn, async SQLAlchemy + asyncpg        |
| Database           | PostgreSQL 16+ with `pgvector` extension            |
| ML / Evaluation    | `all-MiniLM-L6-v2` (384-dim), LLM API (judge)      |
| Frontend           | React 18+, TypeScript, `@xyflow/react`, Tailwind CSS |

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  AGENT LAYER                                                            │
│  ┌──────────────────────┐     OTel-aligned spans     ┌───────────────┐ │
│  │ Multi-Step AI Agent   │ ─────────────────────────► │ Fathom SDK    │ │
│  │ (Search→Summarize→Act)│                            │ @fathom_trace │ │
│  └──────────────────────┘                             └──────┬────────┘ │
└──────────────────────────────────────────────────────────────┼──────────┘
                                                               │
                                              Async HTTP POST (batch)
                                                               │
┌──────────────────────────────────────────────────────────────▼──────────┐
│  FASTAPI MIDDLEWARE LAYER                                               │
│  ┌──────────────────────────┐      ┌──────────────────────────────────┐ │
│  │ Ingestion Gateway        │      │ 3-Phase Evaluation Engine        │ │
│  │ POST /api/v1/traces/runs │      │ ┌────────┐ ┌────────┐ ┌──────┐ │ │
│  │ POST /api/v1/traces/spans│ ────►│ │Phase 1 │→│Phase 2 │→│Phase3│ │ │
│  │ POST /api/v1/traces/     │      │ │Tool    │ │Semantic│ │Judge │ │ │
│  │       spans/batch        │      │ │Check   │ │Drift   │ │LLM   │ │ │
│  └──────────────────────────┘      │ └────────┘ └────────┘ └──────┘ │ │
│                                     └──────────────────────────────────┘ │
│  ┌──────────────────────────┐      ┌──────────────────────────────────┐ │
│  │ Graph Query API          │      │ Time-Travel Rewind Engine        │ │
│  │ GET /api/v1/runs         │      │ POST /api/v1/runs/{id}/rewind   │ │
│  │ GET /api/v1/runs/{id}/dag│      │                                  │ │
│  └──────────────────────────┘      └──────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┬────────────┘
                                                              │
                                                         Read / Write
                                                              │
┌─────────────────────────────────────────────────────────────▼───────────┐
│  PERSISTENCE LAYER  (PostgreSQL + pgvector)                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │  trace_runs   │  │ trace_spans  │  │ evaluations  │                  │
│  │              │◄─┤              │◄─┤              │                  │
│  │  1           │  │  N per run   │  │  N per span  │                  │
│  └──────────────┘  └──────────────┘  └──────────────┘                  │
└────────────────────────────────────────────────────────────────────────┘
                                                              │
                                                     REST + WebSocket
                                                              │
┌─────────────────────────────────────────────────────────────▼───────────┐
│  FRONTEND LAYER  (React + @xyflow/react)                                │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  Interactive DAG Canvas                                            │ │
│  │  ┌─────────────────────┐  ┌─────────────────────────────────────┐ │ │
│  │  │  Developer Mode      │  │  Non-Developer Mode                 │ │ │
│  │  │  • Raw JSON payloads │  │  • Plain-English failure summaries  │ │ │
│  │  │  • Latency / tokens  │  │  • Pass / Warning / Failure badges │ │ │
│  │  │  • Embedding drift   │  │  • Suggested fixes                 │ │ │
│  │  └─────────────────────┘  └─────────────────────────────────────┘ │ │
│  │  ┌─────────────────────────────────────────────────────────────┐  │ │
│  │  │  Node Inspector Panel  (click any node)                     │  │ │
│  │  │  • Input / Output viewer                                    │  │ │
│  │  │  • In-line mutation form (edit prompt / input)              │  │ │
│  │  │  • "Rewind & Re-run" button                                │  │ │
│  │  └─────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Directory Structure

```
Fathom/
├── ARCHITECTURE.md              ← THIS FILE (team reference)
├── LICENSE
├── README.md
├── requirements.txt
├── .env.example
├── docker-compose.yml           ← PostgreSQL + pgvector dev setup
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              ← FastAPI app entry point (Prashlesh)
│   │   ├── config.py            ← Settings via pydantic-settings
│   │   ├── database.py          ← Async SQLAlchemy engine & session (Prashlesh)
│   │   ├── models.py            ← SQLAlchemy ORM models (Prashlesh)
│   │   ├── schemas.py           ← Pydantic request/response schemas (Prashlesh)
│   │   ├── enums.py             ← Shared enums (ALL TEAM MEMBERS USE THIS)
│   │   │
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── ingest.py        ← POST /traces/runs, /traces/spans (Prashlesh)
│   │   │   ├── graph.py         ← GET /runs, /runs/{id}/dag (Rushikesh)
│   │   │   └── rewind.py        ← POST /runs/{id}/rewind (Rushikesh)
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── evaluator.py     ← 3-Phase evaluation orchestrator (Abhishek)
│   │   │   ├── tool_checker.py  ← Phase 1: tool schema validation (Abhishek)
│   │   │   ├── drift_analyzer.py← Phase 2: semantic drift via embeddings (Abhishek)
│   │   │   ├── judge_llm.py     ← Phase 3: LLM-as-a-judge (Abhishek)
│   │   │   └── rewind_engine.py ← Time-travel re-execution logic (Rushikesh)
│   │   │
│   │   └── utils/
│   │       ├── __init__.py
│   │       └── serialization.py ← Safe JSON serialization helpers
│   │
│   ├── migrations/              ← Alembic migration scripts
│   │   └── ...
│   ├── alembic.ini
│   ├── seed_mock_data.py        ← Realistic test data seeder (Prashlesh)
│   └── tests/
│       ├── test_ingest.py
│       ├── test_graph.py
│       ├── test_evaluator.py
│       └── test_rewind.py
│
├── fathom_sdk/                  ← Installable Python package
│   ├── __init__.py
│   ├── tracer.py                ← @fathom_trace decorator (Prashlesh)
│   ├── client.py                ← HTTP client for span flushing (Prashlesh)
│   ├── context.py               ← contextvars definitions (Prashlesh)
│   └── types.py                 ← SDK-side type definitions
│
├── agents/                      ← Test agents for demo/validation
│   ├── search_summarize_act.py  ← Multi-step test agent (Abhishek)
│   └── regression_exporter.py   ← Auto-export failures as tests (Abhishek)
│
└── frontend/                    ← React app
    ├── package.json
    ├── src/
    │   ├── App.tsx
    │   ├── components/
    │   │   ├── DagCanvas.tsx     ← React Flow graph (Swastika)
    │   │   ├── NodeInspector.tsx ← Side panel detail view (Swastika)
    │   │   ├── ModeToggle.tsx   ← Dev / Non-Dev switch (Swastika)
    │   │   └── RewindButton.tsx ← Trigger rewind from UI (Swastika)
    │   ├── hooks/
    │   │   └── useTraceData.ts  ← Data fetching hooks (Swastika)
    │   ├── types/
    │   │   └── api.ts           ← TypeScript types matching Pydantic schemas
    │   └── utils/
    │       └── dagTransform.ts  ← Convert API response to React Flow nodes/edges
    └── ...
```

---

## 4. Shared Enums & Constants

> **CRITICAL:** All team members MUST use these exact enum values. No synonyms, no variations.
> These live in `backend/app/enums.py` and are mirrored in `frontend/src/types/api.ts`.

### SpanStatus
```python
class SpanStatus(str, Enum):
    RUNNING    = "running"      # Span is currently executing
    COMPLETED  = "completed"    # Span finished successfully
    FAILED     = "failed"       # Span threw an exception
    REWOUND    = "rewound"      # Span was mutated & re-executed via time-travel
```

### SpanKind
```python
class SpanKind(str, Enum):
    LLM_CALL       = "llm_call"        # Call to an LLM (OpenAI, Anthropic, etc.)
    TOOL_CALL       = "tool_call"       # External tool/API invocation
    RETRIEVAL       = "retrieval"       # RAG retrieval step
    PROCESSING      = "processing"      # Data transformation / business logic
    AGENT_DECISION  = "agent_decision"  # Agent routing / decision node
```

### EvaluationPhase
```python
class EvaluationPhase(str, Enum):
    TOOL_CHECK      = "tool_check"       # Phase 1: Schema & status code validation
    SEMANTIC_DRIFT  = "semantic_drift"   # Phase 2: Embedding cosine similarity check
    JUDGE_LLM       = "judge_llm"        # Phase 3: LLM-as-a-judge assessment
```

### EvaluationVerdict
```python
class EvaluationVerdict(str, Enum):
    PASS    = "pass"       # No issues detected
    WARNING = "warning"    # Potential issue, non-blocking
    FAILURE = "failure"    # Confirmed failure, needs attention
```

### RunStatus
```python
class RunStatus(str, Enum):
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    REWOUND   = "rewound"     # At least one span was rewound
```

### TypeScript Mirror (frontend)
```typescript
// frontend/src/types/api.ts

export type SpanStatus = 'running' | 'completed' | 'failed' | 'rewound';
export type SpanKind = 'llm_call' | 'tool_call' | 'retrieval' | 'processing' | 'agent_decision';
export type EvaluationPhase = 'tool_check' | 'semantic_drift' | 'judge_llm';
export type EvaluationVerdict = 'pass' | 'warning' | 'failure';
export type RunStatus = 'running' | 'completed' | 'failed' | 'rewound';
```

---

## 5. Database Schema Contracts

### `trace_runs`

| Column           | Type                      | Constraints                 | Notes                              |
| ---------------- | ------------------------- | --------------------------- | ---------------------------------- |
| `id`             | `UUID`                    | PK, default `gen_random_uuid()` |                                    |
| `name`           | `VARCHAR(255)`            | NOT NULL                    | Human-readable run name            |
| `status`         | `VARCHAR(20)`             | NOT NULL, default `running` | Uses `RunStatus` enum              |
| `total_tokens`   | `INTEGER`                 | default `0`                 | Aggregated across all spans        |
| `total_latency_ms` | `FLOAT`                 | default `0.0`               | Wall-clock time for entire run     |
| `metadata`       | `JSONB`                   | default `{}`                | Arbitrary user-supplied metadata   |
| `created_at`     | `TIMESTAMPTZ`             | NOT NULL, default `now()`   | Microsecond precision              |
| `updated_at`     | `TIMESTAMPTZ`             | NOT NULL, default `now()`   | Auto-update on modification        |

### `trace_spans`

| Column           | Type                      | Constraints                 | Notes                              |
| ---------------- | ------------------------- | --------------------------- | ---------------------------------- |
| `id`             | `UUID`                    | PK, default `gen_random_uuid()` | Client-generated, used for idempotency |
| `run_id`         | `UUID`                    | FK → `trace_runs.id`, NOT NULL | Cascade delete with run          |
| `parent_span_id` | `UUID`                    | FK → `trace_spans.id`, NULLABLE | `NULL` = root span of the run   |
| `name`           | `VARCHAR(255)`            | NOT NULL                    | Function/step name                 |
| `kind`           | `VARCHAR(30)`             | NOT NULL                    | Uses `SpanKind` enum               |
| `status`         | `VARCHAR(20)`             | NOT NULL, default `running` | Uses `SpanStatus` enum             |
| `input_data`     | `JSONB`                   | default `{}`                | Serialized function input          |
| `output_data`    | `JSONB`                   | default `{}`                | Serialized function output         |
| `error_message`  | `TEXT`                    | NULLABLE                    | Exception traceback if failed      |
| `latency_ms`     | `FLOAT`                   | NOT NULL                    | Execution time of this span        |
| `token_count`    | `INTEGER`                 | default `0`                 | Tokens used (LLM spans only)       |
| `model_name`     | `VARCHAR(100)`            | NULLABLE                    | e.g., `gpt-4o`, `claude-3.5`      |
| `embedding`      | `VECTOR(384)`             | NULLABLE                    | all-MiniLM-L6-v2 output. Written by evaluator, NOT by ingestion. |
| `metadata`       | `JSONB`                   | default `{}`                | Arbitrary key-value pairs          |
| `created_at`     | `TIMESTAMPTZ`             | NOT NULL, default `now()`   |                                    |
| `updated_at`     | `TIMESTAMPTZ`             | NOT NULL, default `now()`   |                                    |

**Required Indexes:**
```sql
CREATE INDEX idx_spans_run_id ON trace_spans (run_id);
CREATE INDEX idx_spans_parent ON trace_spans (run_id, parent_span_id);
CREATE INDEX idx_spans_embedding ON trace_spans USING hnsw (embedding vector_cosine_ops);
```

**Self-Referential FK:**
```sql
ALTER TABLE trace_spans
ADD CONSTRAINT fk_parent_span
FOREIGN KEY (parent_span_id) REFERENCES trace_spans(id)
ON DELETE SET NULL;
```

### `evaluations`

| Column           | Type                      | Constraints                 | Notes                              |
| ---------------- | ------------------------- | --------------------------- | ---------------------------------- |
| `id`             | `UUID`                    | PK, default `gen_random_uuid()` |                                    |
| `span_id`        | `UUID`                    | FK → `trace_spans.id`, NOT NULL | Cascade delete with span         |
| `phase`          | `VARCHAR(30)`             | NOT NULL                    | Uses `EvaluationPhase` enum        |
| `verdict`        | `VARCHAR(20)`             | NOT NULL                    | Uses `EvaluationVerdict` enum      |
| `score`          | `FLOAT`                   | NULLABLE, range `0.0 – 1.0` | Confidence/similarity score       |
| `details`        | `JSONB`                   | default `{}`                | Phase-specific diagnostic data     |
| `summary`        | `TEXT`                    | NULLABLE                    | Plain-English explanation (Phase 3)|
| `created_at`     | `TIMESTAMPTZ`             | NOT NULL, default `now()`   |                                    |

**Required Indexes:**
```sql
CREATE INDEX idx_eval_span_id ON evaluations (span_id);
CREATE UNIQUE INDEX idx_eval_span_phase ON evaluations (span_id, phase);
```

> **IMPORTANT:** The unique index on `(span_id, phase)` ensures each span gets at most ONE evaluation per phase. Abhishek's evaluator should use `INSERT ... ON CONFLICT (span_id, phase) DO UPDATE` to handle re-evaluations.

### `evaluations.details` JSONB Structure by Phase

**Phase 1 — Tool Check:**
```json
{
  "expected_schema": { "query": "string", "limit": "integer" },
  "actual_payload": { "query": "latest AI news", "limit": 5 },
  "schema_valid": true,
  "http_status": 200,
  "response_time_ms": 342
}
```

**Phase 2 — Semantic Drift:**
```json
{
  "input_embedding_norm": 0.87,
  "output_embedding_norm": 0.82,
  "cosine_similarity": 0.74,
  "drift_threshold": 0.70,
  "drift_detected": false
}
```

**Phase 3 — Judge LLM:**
```json
{
  "judge_model": "gpt-4o-mini",
  "judge_prompt_tokens": 480,
  "judge_completion_tokens": 120,
  "reasoning": "The output correctly summarizes the search results without introducing unsupported claims."
}
```

---

## 6. API Contracts (Pydantic Schemas)

> **These are the contracts.** Frontend types, SDK payloads, and all backend code must conform to these shapes.

### Request Schemas

```python
# ─── Run Creation ───
class RunCreate(BaseModel):
    name: str                              # e.g., "Search-Summarize-Act Pipeline"
    metadata: dict = {}                    # optional user metadata

# ─── Span Creation (single) ───
class SpanCreate(BaseModel):
    id: UUID                               # Client-generated UUID (for idempotency)
    run_id: UUID
    parent_span_id: UUID | None = None     # None = root span
    name: str                              # e.g., "web_search"
    kind: SpanKind                         # "llm_call" | "tool_call" | etc.
    status: SpanStatus                     # "completed" | "failed" | etc.
    input_data: dict = {}
    output_data: dict = {}
    error_message: str | None = None
    latency_ms: float
    token_count: int = 0
    model_name: str | None = None
    metadata: dict = {}

# ─── Span Batch Creation ───
class SpanBatchCreate(BaseModel):
    spans: list[SpanCreate]                # Max 100 spans per batch

# ─── Evaluation Creation (Abhishek's evaluator writes these) ───
class EvaluationCreate(BaseModel):
    span_id: UUID
    phase: EvaluationPhase
    verdict: EvaluationVerdict
    score: float | None = None             # 0.0 – 1.0
    details: dict = {}
    summary: str | None = None

# ─── Rewind Request (Rushikesh's rewind engine) ───
class RewindRequest(BaseModel):
    span_id: UUID                          # The node to mutate
    mutated_input: dict                    # New input_data for this node
    re_execute: bool = True                # If true, re-run downstream spans
```

### Response Schemas

```python
# ─── Run Response ───
class RunResponse(BaseModel):
    id: UUID
    name: str
    status: RunStatus
    total_tokens: int
    total_latency_ms: float
    metadata: dict
    created_at: datetime
    updated_at: datetime
    span_count: int                        # Computed: number of spans in this run

# ─── Span Response (used in DAG assembly) ───
class SpanResponse(BaseModel):
    id: UUID
    run_id: UUID
    parent_span_id: UUID | None
    name: str
    kind: SpanKind
    status: SpanStatus
    input_data: dict
    output_data: dict
    error_message: str | None
    latency_ms: float
    token_count: int
    model_name: str | None
    metadata: dict
    created_at: datetime
    updated_at: datetime
    evaluations: list[EvaluationResponse] = []   # Nested evaluations

# ─── Evaluation Response ───
class EvaluationResponse(BaseModel):
    id: UUID
    span_id: UUID
    phase: EvaluationPhase
    verdict: EvaluationVerdict
    score: float | None
    details: dict
    summary: str | None
    created_at: datetime

# ─── DAG Response (what the frontend consumes) ───
class DagResponse(BaseModel):
    run: RunResponse
    spans: list[SpanResponse]              # Flat list; frontend reconstructs tree
                                           # using parent_span_id references
    root_span_ids: list[UUID]              # Span(s) with parent_span_id = None

# ─── Rewind Response ───
class RewindResponse(BaseModel):
    success: bool
    rewound_span_id: UUID
    downstream_re_executed: list[UUID]     # IDs of spans that were re-run
    new_run_id: UUID | None                # If rewind creates a new run variant
    message: str
```

---

## 7. REST API Endpoints

### Prashlesh — Ingestion Endpoints

| Method | Path                              | Request Body      | Response           | Status  | Notes                    |
| ------ | --------------------------------- | ----------------- | ------------------ | ------- | ------------------------ |
| POST   | `/api/v1/traces/runs`             | `RunCreate`       | `RunResponse`      | `201`   | Creates a new trace run  |
| POST   | `/api/v1/traces/spans`            | `SpanCreate`      | `SpanResponse`     | `201`   | Upserts a single span (idempotent on `id`) |
| POST   | `/api/v1/traces/spans/batch`      | `SpanBatchCreate` | `list[SpanResponse]` | `201` | Upserts up to 100 spans  |

### Rushikesh — Graph Query & Rewind Endpoints

| Method | Path                              | Request Body      | Response           | Status  | Notes                    |
| ------ | --------------------------------- | ----------------- | ------------------ | ------- | ------------------------ |
| GET    | `/api/v1/runs`                    | —                 | `list[RunResponse]`| `200`   | List all runs (paginated)|
| GET    | `/api/v1/runs/{run_id}/dag`       | —                 | `DagResponse`      | `200`   | Full DAG with nested evaluations |
| POST   | `/api/v1/runs/{run_id}/rewind`    | `RewindRequest`   | `RewindResponse`   | `200`   | Mutate node & re-execute downstream |

### Abhishek — Evaluation Endpoints

| Method | Path                              | Request Body        | Response              | Status | Notes                    |
| ------ | --------------------------------- | ------------------- | --------------------- | ------ | ------------------------ |
| POST   | `/api/v1/evaluations`             | `EvaluationCreate`  | `EvaluationResponse`  | `201`  | Store evaluation result  |
| POST   | `/api/v1/spans/{span_id}/evaluate`| —                   | `list[EvaluationResponse]` | `200` | Trigger all 3 phases for a span |

---

## 8. SDK Interface (`@fathom_trace`)

### Basic Usage (what Abhishek's test agent will use)

```python
from fathom_sdk import fathom_trace, FathomClient

# Initialize once
client = FathomClient(
    endpoint="http://localhost:8000/api/v1",
    auto_flush=True,          # Flush spans in background thread
    flush_interval_ms=1000,   # Batch flush every 1 second
)

# Decorate agent steps
@fathom_trace(client=client, kind="tool_call")
def web_search(query: str) -> dict:
    return requests.get(f"https://api.search.com?q={query}").json()

@fathom_trace(client=client, kind="llm_call", model="gpt-4o")
def summarize(search_results: dict) -> str:
    return openai.chat(messages=[...]).content

@fathom_trace(client=client, kind="agent_decision")
def decide_action(summary: str) -> str:
    return "send_email" if "urgent" in summary else "log_only"

# Nested calls automatically form parent → child DAG
@fathom_trace(client=client, kind="processing", name="full_pipeline")
def run_pipeline(query: str):
    results = web_search(query)       # child span 1
    summary = summarize(results)      # child span 2
    action = decide_action(summary)   # child span 3
    return action
```

### What the Decorator Captures Per Span

```json
{
  "id": "uuid-v4 (client-generated)",
  "run_id": "uuid-v4 (from active run context)",
  "parent_span_id": "uuid-v4 or null (from contextvar)",
  "name": "web_search (function name or override)",
  "kind": "tool_call",
  "status": "completed | failed",
  "input_data": { "query": "latest AI news" },
  "output_data": { "results": [...] },
  "error_message": null,
  "latency_ms": 342.5,
  "token_count": 0,
  "model_name": null,
  "metadata": {}
}
```

### SDK Internal Architecture

```
@fathom_trace
    │
    ├── On function entry:
    │   1. Read current parent_span_id from contextvar
    │   2. Generate new span_id (UUID4)
    │   3. Set contextvar to new span_id  ← (save token for reset!)
    │   4. Record start_time
    │
    ├── On function exit (success):
    │   1. Record end_time, compute latency_ms
    │   2. Serialize input_data & output_data (safe JSON)
    │   3. Set status = "completed"
    │   4. Push span to buffer queue
    │   5. Reset contextvar to parent_span_id  ← (CRITICAL: use token.reset())
    │
    ├── On function exit (exception):
    │   1. Record end_time, compute latency_ms
    │   2. Set status = "failed", capture error_message = traceback
    │   3. Push span to buffer queue
    │   4. Reset contextvar to parent_span_id
    │   5. RE-RAISE the exception (decorator must be transparent)
    │
    └── Background flush thread:
        • Every flush_interval_ms, drain the buffer queue
        • POST /api/v1/traces/spans/batch with accumulated spans
        • Retry with exponential backoff on failure
```

> **RULE:** The decorator must support both `def` and `async def` functions.
> Use `inspect.iscoroutinefunction()` to branch.

---

## 9. Evaluation Engine Contract

> **Owner: Abhishek**
> This section defines what Abhishek's evaluator reads and writes.

### Input (what the evaluator reads)
The evaluator reads `trace_spans` rows with `status = 'completed'` that don't yet have all 3 evaluation phases.

### Output (what the evaluator writes)
For each span, the evaluator creates up to 3 `evaluations` rows (one per phase), using the `POST /api/v1/evaluations` endpoint or direct DB writes.

### Evaluation Flow
```
Span Ingested
    │
    ▼
Phase 1: Tool Check
    • Applicable to: kind = "tool_call"
    • Checks: input payload matches expected schema, HTTP status 2xx
    • Writes: EvaluationCreate(phase="tool_check", verdict=..., details=...)
    │
    ▼
Phase 2: Semantic Drift
    • Applicable to: kind = "llm_call" | "processing"
    • Process: Embed input_data & output_data with all-MiniLM-L6-v2
    • Computes: cosine_similarity(input_embedding, output_embedding)
    • Drift threshold: 0.70 (configurable)
    • Also writes the embedding to trace_spans.embedding column (UPDATE)
    • Writes: EvaluationCreate(phase="semantic_drift", score=cosine_sim, ...)
    │
    ▼
Phase 3: Judge LLM
    • Applicable to: ALL spans
    • Sends: span input/output + Phase 1 & 2 results to judge LLM
    • Returns: plain-English summary + final verdict
    • Writes: EvaluationCreate(phase="judge_llm", summary="...", verdict=...)
```

### Score Ranges

| Score Range | Verdict   | Meaning                          |
| ----------- | --------- | -------------------------------- |
| 0.85 – 1.00 | `pass`   | Output is semantically aligned   |
| 0.70 – 0.84 | `warning`| Mild drift, review recommended   |
| 0.00 – 0.69 | `failure`| Significant drift / hallucination|

---

## 10. Time-Travel Rewind Contract

> **Owner: Rushikesh**
> This section defines how the rewind engine works.

### Rewind Flow

```
User clicks "Rewind & Re-run" on a failing node in the UI
    │
    ▼
Frontend sends: POST /api/v1/runs/{run_id}/rewind
    Body: { span_id: "...", mutated_input: {...}, re_execute: true }
    │
    ▼
Rewind Engine:
    1. Validate span_id belongs to run_id
    2. Update the target span's input_data with mutated_input
    3. Mark target span status = "rewound"
    4. Identify all DOWNSTREAM spans (children, grandchildren, etc.)
       using recursive query on parent_span_id
    5. If re_execute = true:
       a. For each downstream span in topological order:
          - Re-invoke the original function with new inputs
          - Record new output_data, latency_ms, status
          - Mark status = "rewound"
       b. Trigger re-evaluation (all 3 phases) on mutated spans
    6. Return RewindResponse with list of affected span IDs
```

### Constraints
- **Only pure LLM calls and processing spans** can be auto-re-executed in v1.
- **Tool calls with side effects** (e.g., sending an email) should be marked as `re_execute: false` and only have their input_data mutated (dry-run mode).
- The rewind engine must NOT modify the original span history. Instead, create new span rows with a `rewind_group_id` linking them to the original.

### Additional Column (Rushikesh to add via migration)

| Column            | Table         | Type     | Notes                               |
| ----------------- | ------------- | -------- | ----------------------------------- |
| `rewind_group_id` | `trace_spans` | `UUID`   | NULLABLE. Groups original + rewound spans |
| `rewind_depth`    | `trace_spans` | `INTEGER`| default `0`. Increments on each rewind |

---

## 11. Frontend Data Flow

> **Owner: Swastika**
> This section defines what data the frontend consumes and how.

### API → React Flow Transformation

```
GET /api/v1/runs/{id}/dag
    │
    ▼
DagResponse {
    run: RunResponse,
    spans: SpanResponse[],
    root_span_ids: UUID[]
}
    │
    ▼
Transform to React Flow format:
    nodes: spans.map(span => ({
        id: span.id,
        type: span.kind,                    // Custom node type per SpanKind
        data: {
            label: span.name,
            status: span.status,
            latency: span.latency_ms,
            tokens: span.token_count,
            verdict: worstVerdict(span.evaluations),   // pass | warning | failure
            // Dev mode extras:
            input: span.input_data,
            output: span.output_data,
            evaluations: span.evaluations,
        },
        position: { x, y }                  // Auto-layout via dagre or elkjs
    }))

    edges: spans
        .filter(s => s.parent_span_id != null)
        .map(span => ({
            id: `${span.parent_span_id}-${span.id}`,
            source: span.parent_span_id,
            target: span.id,
            animated: span.status === 'running',
        }))
```

### Mode Toggle Behavior

| Element             | Developer Mode             | Non-Developer Mode              |
| ------------------- | -------------------------- | ------------------------------- |
| Node label          | Function name              | Plain-English step name         |
| Node badge          | `latency_ms` + `tokens`   | `pass` / `warning` / `failure` |
| Inspector panel     | Raw JSON input/output      | Evaluation `summary` text       |
| Color coding        | By `SpanKind`              | By `EvaluationVerdict`          |
| Mutation form       | JSON editor                | Simple text input               |

### Color Palette

| SpanKind / Verdict   | Color (hex) | Usage                    |
| -------------------- | ----------- | ------------------------ |
| `llm_call`           | `#8B5CF6`   | Purple — AI/LLM nodes    |
| `tool_call`          | `#3B82F6`   | Blue — external tools     |
| `retrieval`          | `#06B6D4`   | Cyan — RAG steps          |
| `processing`         | `#6B7280`   | Gray — logic steps        |
| `agent_decision`     | `#F59E0B`   | Amber — decision nodes    |
| `pass` verdict       | `#22C55E`   | Green — healthy           |
| `warning` verdict    | `#F59E0B`   | Amber — needs review      |
| `failure` verdict    | `#EF4444`   | Red — broken              |

---

## 12. Team Ownership Matrix

| Component                    | Owner       | Depends On            | Blocks          |
| ---------------------------- | ----------- | --------------------- | --------------- |
| DB Schema (`models.py`)      | Prashlesh   | —                     | Everyone        |
| Ingestion API (`ingest.py`)  | Prashlesh   | Schema                | Abhishek, SDK   |
| Pydantic Schemas (`schemas.py`) | Prashlesh | Enums                 | Everyone        |
| Shared Enums (`enums.py`)    | Prashlesh   | —                     | Everyone        |
| SDK (`fathom_sdk/`)          | Prashlesh   | Ingestion API         | Abhishek        |
| Seed Data (`seed_mock_data.py`) | Prashlesh | Schema, Ingestion API | Rushikesh, Swastika |
| Evaluator (`services/evaluator.py`) | Abhishek | Schema, Spans table | Swastika (needs eval data) |
| Test Agent (`agents/`)       | Abhishek    | SDK                   | Demo            |
| Regression Exporter          | Abhishek    | Evaluator, Spans      | —               |
| Graph API (`graph.py`)       | Rushikesh   | Schema, Seed Data     | Swastika        |
| Rewind Engine (`rewind.py`)  | Rushikesh   | Schema, Graph API     | Swastika        |
| DAG Canvas (`DagCanvas.tsx`) | Swastika    | Graph API, Schemas    | —               |
| Node Inspector               | Swastika    | Graph API, Evaluator  | —               |
| Rewind UI                    | Swastika    | Rewind API            | —               |

### Critical Path (blocking order)

```
Prashlesh: enums.py → schemas.py → models.py → database.py → ingest.py → seed_mock_data.py → SDK
                 │          │            │                          │              │
                 ▼          ▼            ▼                          ▼              ▼
          All members  All members  Rushikesh+Abhishek       Abhishek      Rushikesh+Swastika
```

---

## 13. Git Workflow & Branch Strategy

### Branch Naming

```
main                           ← Protected. Merge via PR only.
├── dev                        ← Integration branch. All features merge here first.
│   ├── feat/prashlesh/schema-and-ingestion
│   ├── feat/abhishek/evaluation-engine
│   ├── feat/rushikesh/graph-api-and-rewind
│   └── feat/swastika/react-flow-ui
```

### Rules

1. **Never push directly to `main` or `dev`.**
2. **All PRs require at least 1 review** from another team member.
3. **Prashlesh's schema PR must merge to `dev` first** before anyone else opens a PR.
4. **Commit message format:** `[component] brief description`
   - `[schema] add trace_spans self-referential FK`
   - `[sdk] handle async function tracing`
   - `[eval] implement Phase 2 semantic drift`
   - `[ui] add node inspector side panel`
5. **If you need to change a shared file** (`enums.py`, `schemas.py`, `models.py`), coordinate with Prashlesh first.

---

## 14. Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 16+ with `pgvector` extension
- Docker & Docker Compose (recommended)

### Quick Start

```bash
# 1. Clone & enter repo
git clone https://github.com/<org>/Fathom.git
cd Fathom

# 2. Start PostgreSQL with pgvector
docker-compose up -d postgres

# 3. Backend setup
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 4. Run migrations
alembic upgrade head

# 5. Seed mock data
python seed_mock_data.py

# 6. Start backend
uvicorn app.main:app --reload --port 8000

# 7. Frontend setup (separate terminal)
cd frontend
npm install
npm run dev
```

### Environment Variables (`.env`)

```env
# Database
DATABASE_URL=postgresql+asyncpg://fathom:fathom@localhost:5432/fathom

# Embedding Model (Abhishek)
EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2

# Judge LLM (Abhishek)
JUDGE_LLM_API_KEY=sk-...
JUDGE_LLM_MODEL=gpt-4o-mini

# SDK
FATHOM_ENDPOINT=http://localhost:8000/api/v1
```

---

## 15. Dependency Map & Blocking Order

```mermaid
graph TD
    A[enums.py] --> B[schemas.py]
    A --> C[models.py]
    B --> D[ingest.py]
    C --> D
    C --> E[database.py]
    E --> D
    D --> F[seed_mock_data.py]
    D --> G[fathom_sdk / tracer.py]
    F --> H[graph.py - Rushikesh]
    F --> I[DagCanvas.tsx - Swastika]
    G --> J[test agent - Abhishek]
    C --> K[evaluator.py - Abhishek]
    H --> I
    K --> I
    H --> L[rewind.py - Rushikesh]
    L --> M[RewindButton.tsx - Swastika]

    style A fill:#22C55E,color:#000
    style B fill:#22C55E,color:#000
    style C fill:#22C55E,color:#000
    style D fill:#22C55E,color:#000
    style E fill:#22C55E,color:#000
    style F fill:#22C55E,color:#000
    style G fill:#22C55E,color:#000
    style H fill:#3B82F6,color:#fff
    style I fill:#F59E0B,color:#000
    style J fill:#8B5CF6,color:#fff
    style K fill:#8B5CF6,color:#fff
    style L fill:#3B82F6,color:#fff
    style M fill:#F59E0B,color:#000
```

**Legend:** 🟢 Prashlesh | 🔵 Rushikesh | 🟣 Abhishek | 🟡 Swastika

---

> **Questions? Disagreements?** Open a GitHub Issue tagged `[architecture]` or message in the team chat. Schema changes require Prashlesh's approval.
