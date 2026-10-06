"""Graph and Run Query Endpoints.

Provides endpoints to list agent runs and fetch complete causal DAGs
for visualization in React Flow. Includes root-cause attribution (F-01).

Owner: Abhishek (formerly Rushikesh)
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.database import get_db
from app.enums import EvaluationVerdict
from app.models import Evaluation, SpanLink, TraceRun, TraceSpan
from app.schemas import (
    DagResponse,
    EvaluationResponse,
    RootCauseAttribution,
    RunResponse,
    SpanLinkResponse,
    SpanResponse,
)
from app.utils.verdict import compute_effective_verdict

logger = logging.getLogger("fathom.graph")

router = APIRouter(prefix="/api/v1/runs", tags=["Graph & Runs"])


def _eval_to_response(evaluation: Evaluation) -> EvaluationResponse:
    """Convert an Evaluation ORM model to EvaluationResponse."""
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


def _compute_root_cause_attribution(
    spans: list[TraceSpan],
    span_responses: list[SpanResponse],
    links: list[SpanLink],
) -> RootCauseAttribution | None:
    """Implement F-01 Root-Cause Attribution algorithm (Section 17.2).

    1. Uses effective verdict for every span.
    2. Identifies all non-pass spans (warning / failure).
    3. Walks up ancestors (via parent_span_id and span_links) to find the earliest non-pass ancestor.
    4. Labels originating vs propagated errors and returns the primary root cause.
    """
    span_by_id = {s.id: s for s in spans}
    resp_by_id = {r.id: r for r in span_responses}

    # Map each span to all its upstream predecessors (parent + incoming data links)
    predecessors: dict[UUID, list[UUID]] = {s.id: [] for s in spans}
    for s in spans:
        if s.parent_span_id and s.parent_span_id in span_by_id:
            predecessors[s.id].append(s.parent_span_id)

    for link in links:
        if link.to_span_id in predecessors and link.from_span_id in span_by_id:
            predecessors[link.to_span_id].append(link.from_span_id)

    non_pass_spans = [
        r for r in span_responses
        if r.effective_verdict in (EvaluationVerdict.WARNING, EvaluationVerdict.FAILURE)
    ]

    if not non_pass_spans:
        return None

    # Sort non-pass spans by creation time (earliest first)
    non_pass_spans.sort(key=lambda x: x.created_at)

    # For each non-pass span, find if any of its ancestors are also non-pass
    originating_candidates: list[SpanResponse] = []

    for item in non_pass_spans:
        # Check all ancestors
        has_non_pass_ancestor = False
        visited = set()
        queue = list(predecessors.get(item.id, []))

        while queue:
            ancestor_id = queue.pop(0)
            if ancestor_id in visited:
                continue
            visited.add(ancestor_id)

            ancestor_resp = resp_by_id.get(ancestor_id)
            if ancestor_resp and ancestor_resp.effective_verdict in (
                EvaluationVerdict.WARNING,
                EvaluationVerdict.FAILURE,
            ):
                has_non_pass_ancestor = True
                break

            for p in predecessors.get(ancestor_id, []):
                if p not in visited:
                    queue.append(p)

        if not has_non_pass_ancestor:
            item.is_root_cause = True
            item.root_cause_type = "originating"
            originating_candidates.append(item)
        else:
            item.is_root_cause = False
            item.root_cause_type = "propagated"

    # The primary root cause is the earliest originating span
    primary_origin = originating_candidates[0] if originating_candidates else non_pass_spans[0]
    primary_origin.is_root_cause = True

    # Build path from primary origin to final failing leaf
    path = [primary_origin.id]
    curr = primary_origin.id
    for item in non_pass_spans:
        if item.id != curr and curr in predecessors.get(item.id, []):
            path.append(item.id)
            curr = item.id

    explanation = (
        f"Step '{primary_origin.name}' first introduced an issue with verdict "
        f"'{primary_origin.effective_verdict.value if primary_origin.effective_verdict else 'failure'}'. "
        f"Subsequent failures likely propagated downstream from this step."
    )

    return RootCauseAttribution(
        span_id=primary_origin.id,
        confidence=0.92 if primary_origin.effective_verdict == EvaluationVerdict.FAILURE else 0.78,
        path=path,
        explanation=explanation,
    )


# ──────────────────────────────────────────
# GET /api/v1/runs — List runs with pagination
# ──────────────────────────────────────────


@router.get(
    "",
    response_model=list[RunResponse],
    summary="List agent runs with pagination and span counts",
)
async def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List runs ordered newest first with computed span_count in a single query.

    Avoids N+1 query overhead by using a correlated scalar subquery for span counting.
    """
    span_count_subq = (
        select(func.count(TraceSpan.id))
        .where(TraceSpan.run_id == TraceRun.id)
        .scalar_subquery()
    )

    query = (
        select(TraceRun, span_count_subq.label("span_count"))
        .order_by(TraceRun.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.all()

    runs_response: list[RunResponse] = []
    for run, count in rows:
        runs_response.append(
            RunResponse(
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
                span_count=count or 0,
            )
        )

    return runs_response


# ──────────────────────────────────────────
# GET /api/v1/runs/{run_id}/dag — Full causal DAG
# ──────────────────────────────────────────


@router.get(
    "/{run_id}/dag",
    response_model=DagResponse,
    summary="Get full causal DAG tree with evaluations for a run",
)
async def get_run_dag(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Fetch complete causal execution tree for rendering in React Flow.

    - Excludes heavy vector embeddings from serialization.
    - Resolves root nodes (handling potential out-of-order parent ingestion).
    - Computes effective verdict per span (Section 15.4).
    - Computes root-cause attribution (F-01).
    - Returns 404 if run not found.
    """
    # 1. Fetch Run + Span Count
    span_count_subq = (
        select(func.count(TraceSpan.id))
        .where(TraceSpan.run_id == TraceRun.id)
        .scalar_subquery()
    )

    run_result = await db.execute(
        select(TraceRun, span_count_subq.label("span_count")).where(TraceRun.id == run_id)
    )
    run_row = run_result.first()
    if not run_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )
    run, count = run_row

    # 2. Fetch Spans with evaluations (deferring embedding to save bandwidth)
    spans_result = await db.execute(
        select(TraceSpan)
        .where(TraceSpan.run_id == run_id)
        .options(
            defer(TraceSpan.embedding),
            selectinload(TraceSpan.evaluations),
        )
        .order_by(TraceSpan.created_at.asc())
    )
    spans = list(spans_result.scalars().all())

    # 3. Fetch Span Links (data-flow edges)
    links_result = await db.execute(
        select(SpanLink).where(SpanLink.run_id == run_id)
    )
    links = list(links_result.scalars().all())

    # 4. Convert spans to response models and compute effective verdicts
    span_ids_set = {span.id for span in spans}
    span_responses: list[SpanResponse] = []

    for span in spans:
        eval_resps = [_eval_to_response(e) for e in span.evaluations] if span.evaluations else []
        eff_verdict = compute_effective_verdict(eval_resps) if eval_resps else None

        span_responses.append(
            SpanResponse(
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
                evaluations=eval_resps,
                effective_verdict=eff_verdict,
            )
        )

    # 5. Compute root spans (parent is None OR parent was not ingested)
    root_span_ids = [
        span.id
        for span in spans
        if span.parent_span_id is None or span.parent_span_id not in span_ids_set
    ]

    # 6. Compute Root-Cause Attribution (F-01)
    root_cause = _compute_root_cause_attribution(spans, span_responses, links)

    return DagResponse(
        run=RunResponse(
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
            span_count=count or 0,
        ),
        spans=span_responses,
        root_span_ids=root_span_ids,
        links=[
            SpanLinkResponse(
                id=link.id,
                run_id=link.run_id,
                from_span_id=link.from_span_id,
                to_span_id=link.to_span_id,
                link_type=link.link_type,
            )
            for link in links
        ],
        root_cause=root_cause,
    )
