"""Telemetry ingestion endpoints.

Handles creation and upsert of trace runs and spans.
These are the first endpoints the SDK calls to ship telemetry data.

Owner: Prashlesh
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Evaluation, TraceRun, TraceSpan
from app.schemas import (
    EvaluationCreate,
    EvaluationResponse,
    RunCreate,
    RunResponse,
    SpanBatchCreate,
    SpanCreate,
    SpanResponse,
)

router = APIRouter(prefix="/api/v1/traces", tags=["Telemetry Ingestion"])


# ──────────────────────────────────────────
# Helper: convert ORM model → Pydantic response
# ──────────────────────────────────────────


from app.utils.verdict import compute_effective_verdict
from sqlalchemy import case


def _run_to_response(run: TraceRun, span_count: int = 0) -> RunResponse:
    """Convert a TraceRun ORM instance to a RunResponse."""
    return RunResponse(
        id=run.id,
        name=run.name,
        status=run.status,
        total_tokens=run.total_tokens,
        total_latency_ms=run.total_latency_ms,
        metadata=run.metadata_ or {},
        has_rewinds=run.has_rewinds,
        active_group_id=run.active_group_id,
        created_at=run.created_at,
        updated_at=run.updated_at,
        span_count=span_count,
    )


def _eval_to_response(evaluation: Evaluation) -> EvaluationResponse:
    """Convert an Evaluation ORM instance to an EvaluationResponse."""
    return EvaluationResponse(
        id=evaluation.id,
        span_id=evaluation.span_id,
        phase=evaluation.phase,
        verdict=evaluation.verdict,
        score=evaluation.score,
        details=evaluation.details or {},
        summary=evaluation.summary,
        evaluator_version=evaluation.evaluator_version,
        evaluator_model=evaluation.evaluator_model,
        prompt_hash=evaluation.prompt_hash,
        error_message=evaluation.error_message,
        created_at=evaluation.created_at,
    )


def _span_to_response(span: TraceSpan) -> SpanResponse:
    """Convert a TraceSpan ORM instance to a SpanResponse."""
    eval_responses = [_eval_to_response(e) for e in span.evaluations] if span.evaluations else []
    eff_verdict = compute_effective_verdict(eval_responses) if eval_responses else None

    return SpanResponse(
        id=span.id,
        run_id=span.run_id,
        parent_span_id=span.parent_span_id,
        name=span.name,
        kind=span.kind,
        status=span.status,
        input_data=span.input_data or {},
        output_data=span.output_data or {},
        error_message=span.error_message,
        latency_ms=span.latency_ms,
        token_count=span.token_count,
        model_name=span.model_name,
        metadata=span.metadata_ or {},
        started_at=span.started_at,
        ended_at=span.ended_at,
        rewind_group_id=span.rewind_group_id,
        rewind_depth=span.rewind_depth or 0,
        origin_span_id=span.origin_span_id,
        side_effects=span.side_effects or "unknown",
        cost_usd=float(span.cost_usd) if span.cost_usd is not None else None,
        created_at=span.created_at,
        updated_at=span.updated_at,
        evaluations=eval_responses,
        effective_verdict=eff_verdict,
    )


# ──────────────────────────────────────────
# POST /api/v1/traces/runs — Create a new run
# ──────────────────────────────────────────


@router.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new trace run",
)
async def create_run(
    payload: RunCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new trace run.

    A run is the top-level container for all spans (steps) in a single
    agent execution. The SDK calls this once at the start of a pipeline.
    """
    run = TraceRun(
        name=payload.name,
        metadata_=payload.metadata,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)

    return _run_to_response(run, span_count=0)


# ──────────────────────────────────────────
# POST /api/v1/traces/spans — Upsert a single span
# ──────────────────────────────────────────


async def _upsert_span(span_data: SpanCreate, db: AsyncSession) -> TraceSpan:
    """Upsert a single span. Idempotent on span ID.

    Handles edge cases from Section 14:
    - S-01: Child span arrives before parent (no blocking FK/check)
    - S-02: Auto-creates placeholder run if run does not exist yet
    - S-03: Forward-only status updates (running cannot overwrite completed/failed)
    """
    # S-02: Auto-create placeholder run if not already present
    run = await db.get(TraceRun, span_data.run_id)
    if not run:
        run = TraceRun(
            id=span_data.run_id,
            name=f"Run {str(span_data.run_id)[:8]}",
            status="running",
        )
        db.add(run)
        await db.flush()

    # S-03: Upsert using PostgreSQL INSERT ... ON CONFLICT DO UPDATE
    # Protect terminal statuses from being overwritten by delayed 'running' updates
    terminal_statuses = ("completed", "failed", "cancelled", "rewound", "skipped")

    stmt = pg_insert(TraceSpan).values(
        id=span_data.id,
        run_id=span_data.run_id,
        parent_span_id=span_data.parent_span_id,
        name=span_data.name,
        kind=span_data.kind.value,
        status=span_data.status.value,
        input_data=span_data.input_data,
        output_data=span_data.output_data,
        error_message=span_data.error_message,
        latency_ms=span_data.latency_ms,
        token_count=span_data.token_count,
        model_name=span_data.model_name,
        metadata_=span_data.metadata,
        started_at=span_data.started_at,
        ended_at=span_data.ended_at,
        side_effects=span_data.side_effects,
        llm_request=span_data.llm_request,
        cost_usd=span_data.cost_usd,
    )

    # Status update condition: if existing status is in terminal_statuses and incoming is 'running', keep existing
    new_status_expr = case(
        (
            (TraceSpan.status.in_(terminal_statuses)) & (stmt.excluded.status == "running"),
            TraceSpan.status,
        ),
        else_=stmt.excluded.status,
    )

    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "status": new_status_expr,
            "output_data": stmt.excluded.output_data,
            "error_message": stmt.excluded.error_message,
            "latency_ms": stmt.excluded.latency_ms,
            "token_count": stmt.excluded.token_count,
            "metadata": stmt.excluded.metadata,
            "started_at": stmt.excluded.started_at,
            "ended_at": stmt.excluded.ended_at,
            "side_effects": stmt.excluded.side_effects,
            "llm_request": stmt.excluded.llm_request,
            "cost_usd": stmt.excluded.cost_usd,
        },
    )

    await db.execute(stmt)
    await db.flush()

    # Fetch the upserted span with evaluations
    result = await db.execute(
        select(TraceSpan).where(TraceSpan.id == span_data.id)
    )
    span = result.scalar_one()

    # Eagerly load evaluations
    await db.refresh(span, ["evaluations"])

    return span


@router.post(
    "/spans",
    response_model=SpanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update a single span",
)
async def create_span(
    payload: SpanCreate,
    db: AsyncSession = Depends(get_db),
):
    """Upsert a single span.

    Idempotent: if a span with the given ID already exists, it will be
    updated with the new data. This handles network retries gracefully.
    """
    span = await _upsert_span(payload, db)
    return _span_to_response(span)


# ──────────────────────────────────────────
# POST /api/v1/traces/spans/batch — Upsert up to 100 spans
# ──────────────────────────────────────────


@router.post(
    "/spans/batch",
    response_model=list[SpanResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Batch create or update spans (max 100)",
)
async def create_spans_batch(
    payload: SpanBatchCreate,
    db: AsyncSession = Depends(get_db),
):
    """Batch upsert multiple spans in a single request.

    Accepts up to 100 spans. Each span is individually upserted.
    This is the primary endpoint the SDK uses for efficient telemetry shipping.
    """
    results = []
    for span_data in payload.spans:
        span = await _upsert_span(span_data, db)
        results.append(_span_to_response(span))

    return results


# ──────────────────────────────────────────
# Evaluation ingestion (for Abhishek's evaluator)
# ──────────────────────────────────────────


eval_router = APIRouter(prefix="/api/v1", tags=["Evaluations"])


@eval_router.post(
    "/evaluations",
    response_model=EvaluationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store an evaluation result",
)
async def create_evaluation(
    payload: EvaluationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Store an evaluation result for a span.

    Uses upsert on (span_id, phase) — each span gets at most one
    evaluation per phase. Re-evaluations overwrite previous results.
    """
    # Verify the span exists
    span = await db.get(TraceSpan, payload.span_id)
    if not span:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Span {payload.span_id} not found",
        )

    stmt = pg_insert(Evaluation).values(
        span_id=payload.span_id,
        phase=payload.phase.value,
        verdict=payload.verdict.value,
        score=payload.score,
        details=payload.details,
        summary=payload.summary,
        evaluator_version=payload.evaluator_version,
        evaluator_model=payload.evaluator_model,
        prompt_hash=payload.prompt_hash,
        error_message=payload.error_message,
    )

    stmt = stmt.on_conflict_do_update(
        constraint="uq_eval_span_phase",
        set_={
            "verdict": stmt.excluded.verdict,
            "score": stmt.excluded.score,
            "details": stmt.excluded.details,
            "summary": stmt.excluded.summary,
            "evaluator_version": stmt.excluded.evaluator_version,
            "evaluator_model": stmt.excluded.evaluator_model,
            "prompt_hash": stmt.excluded.prompt_hash,
            "error_message": stmt.excluded.error_message,
        },
    )

    await db.execute(stmt)
    await db.flush()

    # Fetch the upserted evaluation
    result = await db.execute(
        select(Evaluation).where(
            Evaluation.span_id == payload.span_id,
            Evaluation.phase == payload.phase.value,
        )
    )
    evaluation = result.scalar_one()

    return _eval_to_response(evaluation)
