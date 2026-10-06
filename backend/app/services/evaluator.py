"""3-Phase Evaluation Orchestrator.

Orchestrates execution of:
  - Phase 1: Tool Schema Checker (tool_checker.py)
  - Phase 2: Semantic Drift Detector (drift_analyzer.py)
  - Phase 3: Judge LLM (judge_llm.py)

Persists results into `evaluations` table with UPSERT on (span_id, phase)
and updates `trace_spans.embedding` with 384-dim dense vectors.

Owner: Abhishek
"""

import logging
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Evaluation, TraceRun, TraceSpan
from app.schemas import EvaluationCreate
from app.services.drift_analyzer import analyze_semantic_drift
from app.services.judge_llm import evaluate_with_llm
from app.services.tool_checker import validate_tool_span

logger = logging.getLogger("fathom.evaluator")


async def evaluate_span(span: TraceSpan, db: AsyncSession) -> list[Evaluation]:
    """Execute all applicable evaluation phases for a single span.

    Phases executed in order:
      1. Tool Schema Checker (for tool_call spans)
      2. Semantic Drift Detector (for llm_call, processing spans; writes embedding)
      3. Judge LLM (for all spans; incorporates phase 1 & 2 outputs)

    Args:
        span: TraceSpan ORM instance to evaluate.
        db: Active SQLAlchemy AsyncSession.

    Returns:
        List of created/updated Evaluation ORM instances.
    """
    logger.info("Evaluating span %s (%s, kind=%s)", span.id, span.name, span.kind)
    eval_creates: list[EvaluationCreate] = []

    # ─── Phase 1: Tool Check ───
    phase1_eval: EvaluationCreate | None = validate_tool_span(
        span_id=span.id,
        kind=span.kind,
        status=span.status,
        input_data=span.input_data or {},
        output_data=span.output_data or {},
        error_message=span.error_message,
        latency_ms=span.latency_ms,
        metadata=span.metadata_ or {},
    )
    if phase1_eval is not None:
        eval_creates.append(phase1_eval)

    # ─── Phase 2: Semantic Drift ───
    phase2_eval, embedding = analyze_semantic_drift(
        span_id=span.id,
        kind=span.kind,
        input_data=span.input_data or {},
        output_data=span.output_data or {},
    )
    if phase2_eval is not None:
        eval_creates.append(phase2_eval)

    # Update trace_spans.embedding if an embedding was generated
    if embedding is not None:
        await db.execute(
            update(TraceSpan)
            .where(TraceSpan.id == span.id)
            .values(embedding=embedding)
        )

    # ─── Phase 3: Judge LLM ───
    phase3_eval = await evaluate_with_llm(
        span_id=span.id,
        name=span.name,
        kind=span.kind,
        input_data=span.input_data or {},
        output_data=span.output_data or {},
        error_message=span.error_message,
        latency_ms=span.latency_ms,
        phase1_eval=phase1_eval,
        phase2_eval=phase2_eval,
    )
    eval_creates.append(phase3_eval)

    # ─── Persist evaluations with UPSERT on (span_id, phase) ───
    saved_evaluations: list[Evaluation] = []

    for eval_create in eval_creates:
        stmt = pg_insert(Evaluation).values(
            span_id=eval_create.span_id,
            phase=eval_create.phase.value,
            verdict=eval_create.verdict.value,
            score=eval_create.score,
            details=eval_create.details,
            summary=eval_create.summary,
            evaluator_version=eval_create.evaluator_version,
            evaluator_model=eval_create.evaluator_model,
            prompt_hash=eval_create.prompt_hash,
            error_message=eval_create.error_message,
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

    # Query back the saved evaluation rows
    result = await db.execute(
        select(Evaluation).where(Evaluation.span_id == span.id).order_by(Evaluation.created_at)
    )
    saved_evaluations = list(result.scalars().all())

    return saved_evaluations


async def evaluate_run_spans(run_id: UUID, db: AsyncSession) -> list[Evaluation]:
    """Evaluate all spans belonging to a trace run.

    Args:
        run_id: UUID of the trace run.
        db: Active SQLAlchemy AsyncSession.

    Returns:
        List of all Evaluation ORM instances created/updated.
    """
    result = await db.execute(
        select(TraceSpan).where(TraceSpan.run_id == run_id).order_by(TraceSpan.created_at)
    )
    spans = result.scalars().all()

    all_evals: list[Evaluation] = []
    for span in spans:
        evals = await evaluate_span(span, db)
        all_evals.extend(evals)

    return all_evals
