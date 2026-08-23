# Team Task Assignments

> **Before you start anything**, read [ARCHITECTURE.md](./ARCHITECTURE.md) fully. Every schema, enum, API shape, and contract is defined there. If your code doesn't match that file, it's wrong.
>
> Git workflow is in [CONTRIBUTING.md](./CONTRIBUTING.md). Use branches. Create PRs. Don't push to main.

---

## Who Does What

| Person     | Role                         | Branch Name                              |
| ---------- | ---------------------------- | ---------------------------------------- |
| ~~Prashlesh~~ | ~~Foundation & Ingestion~~ | ~~Already working on it~~ ✅              |
| **Abhishek**  | ML & Evaluation Engine    | `feat/abhishek/evaluation-engine`        |
| **Rushikesh** | Backend API & Rewind      | `feat/rushikesh/graph-api-and-rewind`    |
| **Swastika**  | Frontend & UX             | `feat/swastika/react-flow-ui`            |

---

## ⚠️ Before You Start Coding

Prashlesh is building the foundation right now — database tables, ingestion API, shared schemas, enums, and seed data. **Your code will depend on his work.** Here's what that means:

- **Abhishek & Rushikesh**: You can start writing your logic now, but use the Pydantic schemas from [ARCHITECTURE.md → Section 6](./ARCHITECTURE.md#6-api-contracts-pydantic-schemas) as your reference. Once Prashlesh merges his PR, pull `main` and plug your code into the real database.
- **Swastika**: You can start building the React UI and use mock/dummy JSON data that matches the API response shapes from [ARCHITECTURE.md → Section 6](./ARCHITECTURE.md#6-api-contracts-pydantic-schemas). Once the backend APIs are ready, swap the mock data with real API calls.

---

## Abhishek — Evaluation Engine

**Your job:** Build the system that automatically checks every agent step for problems and gives it a pass/warning/failure rating.

**Where your code goes:**
```
backend/app/services/
├── evaluator.py        ← Main orchestrator that runs all 3 phases
├── tool_checker.py     ← Phase 1
├── drift_analyzer.py   ← Phase 2
└── judge_llm.py        ← Phase 3

backend/app/routers/
└── (add your evaluation endpoints here if needed)

agents/
├── search_summarize_act.py   ← Test agent for demo
└── regression_exporter.py    ← Turns failed runs into test cases
```

### What to build (in this order):

**1. Phase 1 — Tool Schema Checker** (`tool_checker.py`)
- For spans where `kind = "tool_call"`, check:
  - Did the input match the expected format? (e.g., was `query` a string, was `limit` a number?)
  - Did the API return a success status (200) or an error (400, 500)?
- Write the result to the `evaluations` table with `phase = "tool_check"`
- See [ARCHITECTURE.md → Section 9](./ARCHITECTURE.md#9-evaluation-engine-contract) for the exact JSONB format

**2. Phase 2 — Semantic Drift Detector** (`drift_analyzer.py`)
- For spans where `kind = "llm_call"` or `"processing"`:
  - Take the `input_data` text and `output_data` text
  - Run both through the `all-MiniLM-L6-v2` model to get 384-dimension vectors
  - Calculate cosine similarity between the two vectors
  - If similarity < 0.70 → the AI probably made stuff up (hallucination)
- Save the embedding to the `trace_spans.embedding` column (UPDATE query)
- Write the result to `evaluations` with `phase = "semantic_drift"`
- Score thresholds are in [ARCHITECTURE.md → Section 9](./ARCHITECTURE.md#9-evaluation-engine-contract)

**3. Phase 3 — Judge LLM** (`judge_llm.py`)
- For ALL spans:
  - Send the span's input, output, AND the results from Phase 1 & 2 to an LLM (like GPT-4o-mini)
  - Ask it: "Is this step's output correct? Explain any problems in plain English."
  - Save the LLM's explanation as the `summary` field in `evaluations` with `phase = "judge_llm"`
- This is what non-technical people will read, so the summary should be **simple and clear**, not technical

**4. Evaluator Orchestrator** (`evaluator.py`)
- Runs Phase 1 → Phase 2 → Phase 3 in order for a given span
- Endpoint: `POST /api/v1/spans/{span_id}/evaluate` — triggers all 3 phases

**5. Test Agent** (`agents/search_summarize_act.py`)
- Build a simple agent that does: Search → Summarize → Decide → Act
- Use Prashlesh's `@fathom_trace` decorator on each step so it gets recorded
- This is our demo agent — it should sometimes fail on purpose so we can show debugging

**6. Regression Exporter** (`agents/regression_exporter.py`)
- Takes a failed run and exports it as a Python test file
- The test should replay the same inputs and check that the outputs don't have the same failure

### Important references:
- Enums you must use: [ARCHITECTURE.md → Section 4](./ARCHITECTURE.md#4-shared-enums--constants) (`EvaluationPhase`, `EvaluationVerdict`)
- Schema to write to: [ARCHITECTURE.md → Section 5 → evaluations table](./ARCHITECTURE.md#5-database-schema-contracts)
- Pydantic model: `EvaluationCreate` and `EvaluationResponse` in [Section 6](./ARCHITECTURE.md#6-api-contracts-pydantic-schemas)
- `details` JSONB format per phase: [ARCHITECTURE.md → Section 5](./ARCHITECTURE.md#5-database-schema-contracts) (search for "Phase 1 — Tool Check")

---

## Rushikesh — Graph API & Rewind Engine

**Your job:** Build the API endpoints that serve the trace data as a tree/graph to the frontend, and build the time-travel rewind feature that lets users fix a broken step and re-run everything after it.

**Where your code goes:**
```
backend/app/routers/
├── graph.py           ← GET endpoints for runs and DAG data
└── rewind.py          ← POST endpoint for time-travel rewind

backend/app/services/
└── rewind_engine.py   ← The actual rewind logic
```

### What to build (in this order):

**1. List Runs API** (`graph.py`)
- `GET /api/v1/runs` — returns a list of all runs (with pagination)
- Response shape: `list[RunResponse]` — see [ARCHITECTURE.md → Section 6](./ARCHITECTURE.md#6-api-contracts-pydantic-schemas)
- Include a `span_count` field (count how many spans belong to each run)

**2. Get DAG API** (`graph.py`)
- `GET /api/v1/runs/{run_id}/dag` — returns the full tree for one run
- This is the **main endpoint the frontend calls**
- Response shape: `DagResponse` — includes the run info, ALL spans (flat list), and which spans are root nodes
- Each span should include its evaluations nested inside (join `evaluations` table)
- The frontend will use `parent_span_id` to reconstruct the tree — you just send a flat list

**3. DAG Assembly Logic**
- Query all spans for a run
- Use the `parent_span_id` column to figure out the parent-child relationships
- You might need a recursive SQL query (`WITH RECURSIVE`) to get all descendants of a node — you'll definitely need this for the rewind feature

**4. Rewind Engine** (`rewind_engine.py` + `rewind.py`)
- `POST /api/v1/runs/{run_id}/rewind`
- Request body: `RewindRequest` — contains which span to fix, the new input data, and whether to re-run downstream steps
- What it does:
  1. Find the span the user wants to fix
  2. Update its `input_data` with the new value the user provided
  3. Mark that span's status as `"rewound"`
  4. Find ALL spans that come after it (children, grandchildren, etc.)
  5. If `re_execute = true`, re-run those downstream spans with the new data flowing through
  6. Return which spans were affected

**Important:** 
- Don't modify the original spans. Create NEW span rows with a `rewind_group_id` that links them back to the originals. This way we keep history.
- You'll need to add `rewind_group_id` (UUID, nullable) and `rewind_depth` (integer, default 0) columns to `trace_spans`. Do this via an Alembic migration.
- For v1, only re-execute spans where `kind = "llm_call"` or `"processing"`. Don't re-execute `"tool_call"` spans automatically (they might have side effects like sending emails). Just mark them as needing manual review.

### Important references:
- Full rewind flow diagram: [ARCHITECTURE.md → Section 10](./ARCHITECTURE.md#10-time-travel-rewind-contract)
- Response schemas: `DagResponse`, `RewindRequest`, `RewindResponse` in [Section 6](./ARCHITECTURE.md#6-api-contracts-pydantic-schemas)
- Endpoint table: [ARCHITECTURE.md → Section 7](./ARCHITECTURE.md#7-rest-api-endpoints)
- Database tables: [ARCHITECTURE.md → Section 5](./ARCHITECTURE.md#5-database-schema-contracts)

---

## Swastika — Frontend & UX

**Your job:** Build the interactive visual interface where users can see the agent's execution as a flowchart, inspect any step, and trigger a rewind.

**Where your code goes:**
```
frontend/src/
├── App.tsx
├── components/
│   ├── DagCanvas.tsx        ← The main graph/flowchart view
│   ├── NodeInspector.tsx    ← Side panel when you click a node
│   ├── ModeToggle.tsx       ← Switch between Dev and Non-Dev mode
│   └── RewindButton.tsx     ← Button to trigger rewind on a node
├── hooks/
│   └── useTraceData.ts      ← Fetch data from backend APIs
├── types/
│   └── api.ts               ← TypeScript types (must match Pydantic schemas)
└── utils/
    └── dagTransform.ts       ← Convert API data to React Flow format
```

### What to build (in this order):

**1. TypeScript Types** (`types/api.ts`)
- Copy the enum values and response shapes from [ARCHITECTURE.md → Section 4](./ARCHITECTURE.md#4-shared-enums--constants) and [Section 6](./ARCHITECTURE.md#6-api-contracts-pydantic-schemas)
- These types must match the backend exactly

**2. Data Fetching** (`hooks/useTraceData.ts`)
- Fetch `GET /api/v1/runs` for the run list
- Fetch `GET /api/v1/runs/{run_id}/dag` for the full graph of a run
- Until the backend is ready, use **mock JSON data** that matches the `DagResponse` shape. This way you can build the UI without waiting.

**3. DAG Canvas** (`DagCanvas.tsx`) — This is the main thing
- Use `@xyflow/react` (React Flow) to render the graph
- Convert the flat list of spans into React Flow nodes and edges:
  - Each span = one node
  - If a span has `parent_span_id`, draw an arrow from parent to child
- Use a layout library like `dagre` or `elkjs` to auto-position nodes (so they don't all stack on top of each other)
- Color code nodes — see the color palette in [ARCHITECTURE.md → Section 11](./ARCHITECTURE.md#11-frontend-data-flow)
- The transformation logic is documented in [ARCHITECTURE.md → Section 11](./ARCHITECTURE.md#11-frontend-data-flow) (the "API → React Flow Transformation" section)

**4. Node Inspector** (`NodeInspector.tsx`)
- When a user clicks on a node, show a side panel with details:
  - In **Dev Mode**: raw JSON of `input_data`, `output_data`, latency, token count, embedding drift score, evaluation details
  - In **Non-Dev Mode**: the `summary` text from the Judge LLM evaluation, a simple pass/warning/failure badge, and what went wrong in plain English
- Include a text input / JSON editor where the user can edit the input of a failing node

**5. Mode Toggle** (`ModeToggle.tsx`)
- A switch/toggle at the top of the page
- **Developer Mode**: Shows technical info (JSON, latency, tokens, drift scores)
- **Non-Developer Mode**: Shows simple info (plain English summaries, pass/fail badges)
- See the full behavior table in [ARCHITECTURE.md → Section 11](./ARCHITECTURE.md#11-frontend-data-flow)

**6. Rewind Button** (`RewindButton.tsx`)
- Appears in the Node Inspector panel for failed nodes
- When clicked, takes the edited input from the inspector form and sends `POST /api/v1/runs/{run_id}/rewind` with the `RewindRequest` body
- After rewind completes, refresh the DAG to show updated node statuses

### Design Notes:
- Use **Tailwind CSS** for styling
- Make it look modern and clean — dark mode preferred
- Node colors by type AND by verdict are defined in [ARCHITECTURE.md → Section 11](./ARCHITECTURE.md#11-frontend-data-flow)
- Animated edges for `status = "running"` nodes
- The graph should be pannable and zoomable (React Flow gives you this for free)

### Important references:
- All TypeScript types: [ARCHITECTURE.md → Section 4](./ARCHITECTURE.md#4-shared-enums--constants) (scroll to "TypeScript Mirror")
- API response shapes: [ARCHITECTURE.md → Section 6](./ARCHITECTURE.md#6-api-contracts-pydantic-schemas)
- How to transform API data to React Flow nodes/edges: [ARCHITECTURE.md → Section 11](./ARCHITECTURE.md#11-frontend-data-flow)
- Color palette: [ARCHITECTURE.md → Section 11](./ARCHITECTURE.md#11-frontend-data-flow) (scroll to "Color Palette")
- What each mode shows: [ARCHITECTURE.md → Section 11](./ARCHITECTURE.md#11-frontend-data-flow) (scroll to "Mode Toggle Behavior")

---

## How to Start Right Now

```bash
# 1. Pull the latest code
git checkout main
git pull origin main

# 2. Create your branch
git checkout -b feat/your-name/your-feature

# 3. Read ARCHITECTURE.md (seriously, read the whole thing)

# 4. Start coding your part

# 5. When done, push and create a PR
git push origin feat/your-name/your-feature
# Then go to GitHub and create a Pull Request
```

---

## Questions?

If something in [ARCHITECTURE.md](./ARCHITECTURE.md) is unclear or you think a schema needs to change — **don't just change it yourself**. Message in the group chat and tag Prashlesh. Schema changes affect everyone.

Good luck team! 💪
