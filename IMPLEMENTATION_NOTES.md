# Fathom Implementation Notes & Development Journal

**Branch:** `feat/abhishek/features-update`  
**Reference Document:** FATHOM Technical Specification and Design Review v1.0 (6 October 2026)  
**Author/Developer:** Abhishek Tiwari (`abhishektiwari8626-ctrl`) & Antigravity  

---

## 🎯 Implementation Roadmap Progress

- [x] **Phase 0: Foundations and Schema Fixes**
  - [x] 0.1: Introduce Alembic migrations (async engine, autogenerate, pgvector support)
  - [x] 0.2: Apply schema changes in 13.3 (`started_at`, `ended_at`, `origin_span_id`, `side_effects`, `llm_request`, `cost_usd`, drop FK on `parent_span_id`, `span_links` table, evaluator columns, HNSW index, `has_rewinds`, `active_group_id`)
  - [x] 0.3: Extend enums: `SpanStatus` (+`pending`, `skipped`, `cancelled`), `EvaluationVerdict` (+`error`) in backend & SDK
  - [x] 0.4: Make ingestion idempotent and order-tolerant (drop parent FK check, placeholder run auto-creation, forward-only status updates)
  - [x] 0.5: Evaluator improvements: record version/model/prompt hash; error verdict on judge failure; upsert semantics; empty results warning
  - [x] 0.6: Implement verdict precedence function (15.4) as a single shared backend utility (`app.utils.verdict`)
- [x] **Phase 1: Graph API**
  - [x] 1.1: `GET /api/v1/runs` with `limit`, `offset`, newest first, `span_count` in single query (no N+1)
  - [x] 1.2: `GET /api/v1/runs/{run_id}/dag` with joined evaluations, `root_span_ids`, no embeddings (defer/exclude), 404 for unknown run
  - [x] 1.3: Include effective verdict per span (15.4), `span_links`, and root-cause attribution (F-01) in response
  - [x] 1.4: Register `graph.py` in `main.py` and write comprehensive tests
- [x] **Phase 2: Rewind MVP**
  - [x] 2.1: Re-execution model (R1 Option B: server-side replay of single `llm_call`, store `llm_request`)
  - [x] 2.2: SDK capture of `llm_request` for LLM spans
  - [x] 2.3: Subtree discovery (8.3) with run filter and depth guard (SQL recursive CTE)
  - [x] 2.4: Branch creation: `rewind_group_id`, `origin_span_id`, `rewind_depth + 1`, original untouched, `has_rewinds = true`
  - [x] 2.5: Side-effect gating: tools cloned as `pending` unless confirmed
  - [x] 2.6: Idempotency key and per-run lock; validate span-in-run, run finished, input shape
  - [x] 2.7: Run re-execution handler (HTTP 200/202)
  - [x] 2.8: Auto-evaluate new spans and register `rewind.py` in `main.py`
- [x] **Phase 3: Frontend**
  - [x] 3.1: Scaffold Vite + React 18 + TypeScript + Tailwind CSS (`@xyflow/react`, `dagre`, `lucide-react`, `axios`)
  - [x] 3.2: `frontend/src/types/api.ts` mirroring Pydantic models and enums exactly
  - [x] 3.3: `dagTransform.ts`: spans to nodes and edges, dagre layout, link edges dashed
  - [x] 3.4: `DagCanvas.tsx` with verdict colors, kind badges, icons (U-02)
  - [x] 3.5: `ModeToggle.tsx` with global mode state (Developer vs Non-Developer)
  - [x] 3.6: `NodeInspector.tsx`: Developer view, Non-Developer view, all phase results
  - [x] 3.7: Rewind editor with JSON validation and diff (U-04); reload DAG on rewind success
  - [x] 3.8: Run list page with filters (U-06); empty and error states (U-09)
- [x] **Phase 4: Differentiators & Enhancements**
  - [x] 4.1: Root-cause attribution algorithm (F-01) in backend graph assembly and visual UI
  - [x] 4.2: Branch switcher and rewind version badges (F-03)
  - [x] 4.3: Seed realistic demonstration data with edge cases (linear success, branching warning, failed hallucination)


---

## 📝 Detailed Log of Changes

### Phase 0: Foundations & Schema Migration
1. **Branch Confirmation**: Verified branch `feat/abhishek/features-update` is active. Never committing to `main`.
2. **PostgreSQL & pgvector Container**: Spun up Docker container `fathom-postgres` with `pgvector/pgvector:pg16` on port 5432.
3. **Enum Extensions (`enums.py` & `schemas.py`)**:
   - `SpanStatus`: Added `PENDING = "pending"`, `SKIPPED = "skipped"`, `CANCELLED = "cancelled"`. Resolves Issue I-1.
   - `EvaluationVerdict`: Added `ERROR = "error"`. Resolves Issue I-12.
4. **Database Models & Alembic Migration (`models.py`, `alembic/`)**:
   - Initialized Async Alembic with `alembic init -t async alembic`.
   - Added `started_at`, `ended_at`, `origin_span_id`, `side_effects`, `llm_request`, `cost_usd` to `TraceSpan`.
   - Dropped hard foreign key constraint on `parent_span_id` while preserving index `idx_spans_parent` to enable out-of-order span ingestion (`S-01`).
   - Added HNSW vector index `idx_spans_embedding` on `trace_spans.embedding` using `vector_cosine_ops`.
   - Added `span_links` table with unique constraint on `(from_span_id, to_span_id, link_type)` to support non-tree multi-parent DAG data flow (`R3`, `13.3`).
   - Added `has_rewinds` and `active_group_id` to `TraceRun` (`R-16`, `R-17`).
   - Added `evaluator_version`, `evaluator_model`, `prompt_hash`, `error_message` to `Evaluation` table (`13.3`, `15.5`).
   - Applied migration `76c608de25f8_initial_schema_with_phase0_fixes.py` successfully to the database.
5. **Verdict Precedence Engine (`app/utils/verdict.py`)**:
   - Implemented exact precedence evaluation algorithm from Section 15.4:
     1. Phase 1 Failure -> Failure (deterministic; never overridden by judge).
     2. Phase 3 Failure -> Failure.
     3. Phase 3 Error (judge unavailable) -> Worst of Phase 1 / Phase 2.
     4. Phase 3 Pass & Phase 2 Failure -> Warning (unconfirmed drift).
     5. Phase 3 Warning -> Warning.
     6. Otherwise -> Pass.
   - Added unit test suite `backend/tests/test_verdict_precedence.py` covering all precedence rules. All 17 tests passed.
6. **Ingestion Edge Cases Handled (`ingest.py`)**:
   - `S-01`: Spans can now arrive before their parents without foreign key failure or 404 rejection.
   - `S-02`: Auto-creates placeholder `TraceRun` if span arrives before its run record.
   - `S-03`: Forward-only status updates: terminal states (`completed`, `failed`, `cancelled`, `rewound`, `skipped`) cannot be overwritten by delayed `running` updates.
   - Evaluator metadata (`evaluator_version`, `evaluator_model`, `prompt_hash`, `error_message`) saved on evaluations upsert.
   - Tool Checker improved: empty results flagged as `warning`, retryable flags on HTTP 429/503/504, caller vs provider error categories recorded.

### Phase 1: Graph API & Root-Cause Attribution
1. **List Runs Endpoint (`GET /api/v1/runs`)**:
   - Single-query execution using correlated scalar subquery for `span_count` (`select(func.count(TraceSpan.id)).where(TraceSpan.run_id == TraceRun.id)`), avoiding N+1 overhead.
   - Pagination support (`limit`, `offset`), sorted by `created_at DESC`.
   - Includes `has_rewinds` flag and `active_group_id`.
2. **DAG Query Endpoint (`GET /api/v1/runs/{run_id}/dag`)**:
   - Fetches complete run metadata with 404 response on missing run.
   - Eagerly loads all `evaluations` in one query with `selectinload(TraceSpan.evaluations)`.
   - Explicitly defers heavy 384-dimensional vector `embedding` to prevent high network latency and payload bloat.
   - Resolves `root_span_ids` robustly (accounts for out-of-order parent ingestion).
   - Joins `span_links` for non-tree DAG representations.
   - Automatically computes `effective_verdict` for each span using Phase 0's precedence engine.
3. **F-01 Root-Cause Attribution Engine**:
   - Implemented `_compute_root_cause_attribution(spans, span_responses, links)`:
     - Detects all non-pass (`warning` / `failure`) spans.
     - Traverses causal ancestors via `parent_span_id` and `span_links`.
     - Identifies earliest `originating` error versus downstream `propagated` errors.
     - Outputs root cause candidate, confidence score, causal path, and plain-English explanation.
4. **Automated Testing Suite (`backend/tests/test_graph.py`)**:
   - Tests run list pagination, field presence, and computed `span_count`.
   - Tests full DAG hierarchy, evaluation nesting, and root-cause attribution on realistic failed pipelines.
   - Tests 404 handling on non-existent runs.
   - All 20 tests in the test suite pass with 100% success rate.

### Phase 2: Time-Travel Rewind Engine
1. **Re-Execution Strategy (Option B per Section 13.2 R1)**:
   - For `llm_call`: Captures `llm_request` with model, parameters, and input. On rewind, replays call with mutated input.
   - For `processing`: Re-executes deterministic transformations.
   - For `tool_call`: Checked against `side_effects`. Write tools (`side_effects in ("write", "unknown")`) are gated and cloned with `status = "pending"` awaiting explicit human confirmation (`R-08`).
2. **Subtree Discovery (`get_downstream_span_ids`)**:
   - Recursive CTE traversal with run isolation and recursion depth limit (< 200) to protect against corrupt cyclic links (`R-09`).
3. **Audit History & Invariant Preservation**:
   - Original failing spans are **never mutated or overwritten** (`R-16`, `I-3`).
   - New branches share an isolated `rewind_group_id` with incremented `rewind_depth` (`depth + 1`) and `origin_span_id` pointing to the original ancestor.
   - Child spans in the new branch re-link their `parent_span_id` to the newly cloned parent in the branch, ensuring a coherent downstream tree.
   - `TraceRun` updated with `has_rewinds = True` and `active_group_id = rewind_group_id`.
4. **Validation & Automated Evaluations**:
   - `R-02`: Rejects mismatched `span_id` / `run_id` with HTTP 422.
   - `R-13`: Rejects rewinding runs that are currently in progress with HTTP 409.
   - `R-15`: Automatically triggers the 3-phase evaluation pipeline on newly branched spans.
5. **Rewind API Endpoint (`POST /api/v1/runs/{run_id}/rewind`)**:
   - Matches Section 16.1 `RewindResponse` specification with `downstream_re_executed`, `downstream_pending_confirmation`, and `estimated_tokens`.
   - Integration tests in `test_rewind.py` pass completely. Full test suite has 23 passing tests.

### Phase 3: Interactive Visual Frontend (`frontend/`)
1. **Tech Stack**:
   - Vite 5 + React 18 + TypeScript + Tailwind CSS 3.4.
   - `@xyflow/react` (React Flow 12) + `dagre` for automated Directed Acyclic Graph topology layout.
   - `lucide-react` icons for accessible state and verdict communication (`U-02`).
   - `axios` configured with proxy `/api` pointing to FastAPI on `http://localhost:8000`.
2. **DAG Transformer & Auto-Layout (`dagTransform.ts`)**:
   - Transformed flat spans array into hierarchical React Flow nodes & edges with top-to-bottom layout (`TB`).
   - Solid arrow edges for direct causal dependencies (`parent_span_id`).
   - Dashed edges for data-flow connections (`span_links`).
   - Animated edges for in-flight running steps (`SpanStatus.RUNNING`).
3. **Custom SpanNode (`SpanNode.tsx`)**:
   - Visual color coding by effective verdict: Emerald (`pass`), Amber (`warning`), Red (`failure`), Purple dashed (`rewound`).
   - Kind badges with custom iconography (`llm_call`, `tool_call`, `retrieval`, `processing`, `agent_decision`).
   - Prominent bouncing badge for **"Likely Root Cause"** (`F-01`, `U-08`).
   - Revision indicator tag `Branch v{rewind_depth}` for branched spans.
4. **Dual-Mode Inspector & Time-Travel Rewind (`NodeInspector.tsx`)**:
   - **Mode Toggle (`ModeToggle.tsx`)**: One-click top-bar switch with persistent state.
   - **Developer View**: Displays raw JSON input/output payloads with copy buttons, exact latency, token counts, Phase 1 HTTP codes, Phase 2 cosine drift scores, and stack traces.
   - **Non-Developer View**: Replaces JSON with Phase 3 Judge LLM plain-English summary, "Why It Matters" (`details.reasoning`), and "Suggested Fix" (`details.suggested_fix`).
   - **Live JSON Mutation Editor (`U-04`)**: Real-time JSON syntax validation; disables rewind action when syntax is invalid.
   - **One-Click Rewind**: Sends `POST /api/v1/runs/{run_id}/rewind` and triggers reactive graph refresh.
5. **Run List & Filter Bar (`RunList.tsx`)**:
   - Search filter by run name.
   - Status filter pills (`All`, `Failed Only`, `Rewound Only`).
   - Step count, total latency, and token totals displayed on each run card.

### Phase 4: System Verification & Validation

1. **Automated Unit & Integration Test Suite**:
   - `backend/tests/test_evaluator.py`: 11 tests covering deterministic Phase 1 tool check, Phase 2 semantic drift cosine similarity, Phase 3 judge LLM, and prompt caching.
   - `backend/tests/test_verdict_precedence.py`: 6 tests verifying strict precedence ordering (`failure > warning > pass`).
   - `backend/tests/test_graph.py`: 3 integration tests verifying `/runs` list pagination, `/dag` node/edge hierarchy, and `F-01` root cause attribution.
   - `backend/tests/test_rewind.py`: 3 tests verifying Option B re-execution, write tool pending gate (`R-08`), and run mismatch rejection (`R-02`).
   - Total tests: **23 passed, 0 failed**.

2. **End-to-End Live Verification**:
   - Verified against Docker Postgres container `fathom-postgres` seeded with realistic multi-step agent traces.
   - Live query of `GET /api/v1/runs/829a28c6-c7fc-4f8e-9246-cd34176083a3/dag` identified `score_lead_with_llm` as the origin failure (`is_root_cause: true`, confidence: 0.92) and downstream `assign_to_sales_team` as propagated.
   - Live execution of `POST /api/v1/runs/829a28c6-c7fc-4f8e-9246-cd34176083a3/rewind` generated a new branch (`rewind_depth: 1`, `rewind_group_id`), cloned the write tool as `status: pending` awaiting confirmation, preserved the original failing span untouched (`R-16`, `I-3`), and re-evaluated the newly created spans.
   - Production Vite frontend build (`npm run build`) succeeded with 0 TypeScript and bundling errors.

3. **Git Branch and Commit History**:
   - All commits strictly created on branch: `feat/abhishek/features-update`.
   - `main` branch was left completely untouched.

---

## How to Run Locally

### 1. Database
Ensure the `fathom-postgres` container is running:
```bash
docker start fathom-postgres
```

### 2. Backend (FastAPI)
```bash
cd backend
../venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Swagger API docs available at: `http://localhost:8000/docs`.

### 3. Frontend (React 18 + React Flow + Tailwind)
```bash
cd frontend
npm run dev
```
Open `http://localhost:5173` in your browser.
