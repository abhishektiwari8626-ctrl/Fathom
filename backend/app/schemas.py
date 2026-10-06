"""Pydantic request/response schemas — the API contract.

These schemas define the exact JSON shapes for all API communication.
Frontend TypeScript types, SDK payloads, and all backend code must match these.
See ARCHITECTURE.md Section 6 for the full contract.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import (
    EvaluationPhase,
    EvaluationVerdict,
    RunStatus,
    SpanKind,
    SpanStatus,
)


# ──────────────────────────────────────────
# Request Schemas
# ──────────────────────────────────────────


class RunCreate(BaseModel):
    """Create a new trace run."""

    name: str = Field(..., max_length=255, examples=["Search-Summarize-Act Pipeline"])
    metadata: dict = Field(default_factory=dict)


class SpanCreate(BaseModel):
    """Create or upsert a single span.

    The `id` is client-generated (UUID4) for idempotency.
    If a span with this id already exists, it will be updated.
    """

    id: UUID
    run_id: UUID
    parent_span_id: UUID | None = None
    name: str = Field(..., max_length=255, examples=["web_search"])
    kind: SpanKind
    status: SpanStatus
    input_data: dict = Field(default_factory=dict)
    output_data: dict = Field(default_factory=dict)
    error_message: str | None = None
    latency_ms: float = Field(default=0.0, ge=0)
    token_count: int = Field(default=0, ge=0)
    model_name: str | None = Field(default=None, max_length=100)
    metadata: dict = Field(default_factory=dict)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    side_effects: str = Field(default="unknown", max_length=10)
    llm_request: dict | None = None
    cost_usd: float | None = None


class SpanBatchCreate(BaseModel):
    """Batch create/upsert multiple spans (max 100 per request)."""

    spans: list[SpanCreate] = Field(..., max_length=100)


class EvaluationCreate(BaseModel):
    """Store an evaluation result for a span.

    Used by Abhishek's evaluation engine.
    """

    span_id: UUID
    phase: EvaluationPhase
    verdict: EvaluationVerdict
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    details: dict = Field(default_factory=dict)
    summary: str | None = None
    evaluator_version: str | None = None
    evaluator_model: str | None = None
    prompt_hash: str | None = None
    error_message: str | None = None


class RewindRequest(BaseModel):
    """Request to rewind a span and re-execute downstream.

    Used by Rushikesh's rewind engine.
    """

    span_id: UUID
    mutated_input: dict
    re_execute: bool = True


# ──────────────────────────────────────────
# Response Schemas
# ──────────────────────────────────────────


class EvaluationResponse(BaseModel):
    """Evaluation result returned to clients."""

    id: UUID
    span_id: UUID
    phase: EvaluationPhase
    verdict: EvaluationVerdict
    score: float | None
    details: dict
    summary: str | None
    evaluator_version: str | None = None
    evaluator_model: str | None = None
    prompt_hash: str | None = None
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SpanResponse(BaseModel):
    """Span data returned to clients, with nested evaluations."""

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
    started_at: datetime | None = None
    ended_at: datetime | None = None
    rewind_group_id: UUID | None = None
    rewind_depth: int = 0
    origin_span_id: UUID | None = None
    side_effects: str = "unknown"
    cost_usd: float | None = None
    created_at: datetime
    updated_at: datetime
    evaluations: list[EvaluationResponse] = []

    # Computed fields for graph UI & analysis (15.4, F-01)
    effective_verdict: EvaluationVerdict | None = None
    is_root_cause: bool = False
    root_cause_type: str | None = None  # "originating" | "propagated"

    model_config = {"from_attributes": True}


class RunResponse(BaseModel):
    """Run data returned to clients."""

    id: UUID
    name: str
    status: RunStatus
    total_tokens: int
    total_latency_ms: float
    metadata: dict
    has_rewinds: bool = False
    active_group_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    span_count: int = 0

    model_config = {"from_attributes": True}


class SpanLinkResponse(BaseModel):
    """Data-flow edge between spans (Section 13.3)."""

    id: UUID
    run_id: UUID
    from_span_id: UUID
    to_span_id: UUID
    link_type: str = "data"

    model_config = {"from_attributes": True}


class RootCauseAttribution(BaseModel):
    """Root-cause attribution payload (Section 17.2, F-01)."""

    span_id: UUID
    confidence: float = 0.85
    path: list[UUID] = Field(default_factory=list)
    explanation: str


class DagResponse(BaseModel):
    """Full DAG for a run — what the frontend consumes.

    Spans are a flat list. The frontend reconstructs the tree
    using parent_span_id references and span_links.
    """

    run: RunResponse
    spans: list[SpanResponse]
    root_span_ids: list[UUID]
    links: list[SpanLinkResponse] = Field(default_factory=list)
    root_cause: RootCauseAttribution | None = None


class RewindResponse(BaseModel):
    """Result of a rewind operation (Section 16.1)."""

    success: bool
    rewind_group_id: UUID
    rewound_span_id: UUID
    downstream_re_executed: list[UUID] = Field(default_factory=list)
    downstream_pending_confirmation: list[UUID] = Field(default_factory=list)
    downstream_skipped: list[UUID] = Field(default_factory=list)
    estimated_tokens: int = 0
    status: str = "completed"
    new_run_id: UUID | None = None
    message: str

