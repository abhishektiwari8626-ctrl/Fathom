"""Evaluation API endpoints.

Handles triggering evaluation runs on spans and runs, and storing evaluations.

Owner: Abhishek
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Evaluation, TraceRun, TraceSpan
from app.schemas import EvaluationCreate, EvaluationResponse
from app.services.evaluator import evaluate_run_spans, evaluate_span

router = APIRouter(prefix="/api/v1", tags=["Evaluations"])


def _eval_to_response(evaluation: Evaluation) -> EvaluationResponse:
    """Convert an Evaluation ORM model to an EvaluationResponse."""
    return EvaluationResponse(
        id=evaluation.id,
        span_id=evaluation.span_id,
        phase=evaluation.phase,
        verdict=evaluation.verdict,
        score=evaluation.score,
        details=evaluation.details or {},
        summary=evaluation.summary,
        created_at=evaluation.created_at,
    )


@router.post(
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
    )

    stmt = stmt.on_conflict_do_update(
        constraint="uq_eval_span_phase",
        set_={
            "verdict": stmt.excluded.verdict,
            "score": stmt.excluded.score,
            "details": stmt.excluded.details,
            "summary": stmt.excluded.summary,
        },
    )

    await db.execute(stmt)
    await db.flush()

    result = await db.execute(
        select(Evaluation).where(
            Evaluation.span_id == payload.span_id,
            Evaluation.phase == payload.phase.value,
        )
    )
    evaluation = result.scalar_one()

    return _eval_to_response(evaluation)


@router.post(
    "/spans/{span_id}/evaluate",
    response_model=list[EvaluationResponse],
    status_code=status.HTTP_200_OK,
    summary="Trigger all 3 evaluation phases for a span",
)
async def trigger_span_evaluation(
    span_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Trigger Phase 1, Phase 2, and Phase 3 evaluation for a given span.

    Saves results to the database and returns all generated evaluation records.
    """
    span = await db.get(TraceSpan, span_id)
    if not span:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Span {span_id} not found",
        )

    evaluations = await evaluate_span(span, db)
    await db.commit()

    return [_eval_to_response(e) for e in evaluations]


@router.post(
    "/runs/{run_id}/evaluate",
    response_model=list[EvaluationResponse],
    status_code=status.HTTP_200_OK,
    summary="Trigger evaluation for all spans in a run",
)
async def trigger_run_evaluation(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Trigger evaluation across all spans of a given trace run."""
    run = await db.get(TraceRun, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )

    evaluations = await evaluate_run_spans(run_id, db)
    await db.commit()

    return [_eval_to_response(e) for e in evaluations]
