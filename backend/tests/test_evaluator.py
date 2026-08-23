"""Comprehensive unit and integration tests for Abhishek's Evaluation Engine.

Tests:
  - Phase 1: Tool Schema Checker (tool_checker.py)
  - Phase 2: Semantic Drift Detector (drift_analyzer.py)
  - Phase 3: Judge LLM (judge_llm.py)
  - Evaluator Orchestrator (evaluator.py)
  - FastAPI Evaluation Endpoints (/api/v1/spans/{span_id}/evaluate)
"""

import uuid
import pytest
from unittest.mock import AsyncMock, patch

from app.enums import EvaluationPhase, EvaluationVerdict, SpanKind, SpanStatus
from app.models import Evaluation, TraceRun, TraceSpan
from app.schemas import EvaluationCreate, SpanCreate
from app.services.drift_analyzer import (
    _compute_cosine_similarity,
    analyze_semantic_drift,
    generate_embedding,
)
from app.services.judge_llm import evaluate_with_llm
from app.services.tool_checker import validate_tool_span


# ──────────────────────────────────────────
# Phase 1: Tool Schema Checker Tests
# ──────────────────────────────────────────

def test_tool_checker_success():
    """Verify tool check passes on valid 200 response and correct types."""
    span_id = uuid.uuid4()
    eval_result = validate_tool_span(
        span_id=span_id,
        kind=SpanKind.TOOL_CALL,
        status=SpanStatus.COMPLETED,
        input_data={"query": "latest AI trends", "limit": 5},
        output_data={"status_code": 200, "results": ["item1", "item2"]},
        latency_ms=150.0,
        metadata={"expected_schema": {"query": "string", "limit": "integer"}},
    )

    assert eval_result is not None
    assert eval_result.phase == EvaluationPhase.TOOL_CHECK
    assert eval_result.verdict == EvaluationVerdict.PASS
    assert eval_result.score == 1.0
    assert eval_result.details["schema_valid"] is True
    assert eval_result.details["http_status"] == 200
    assert eval_result.details["response_time_ms"] == 150.0


def test_tool_checker_http_error():
    """Verify tool check fails when HTTP status code is 500."""
    span_id = uuid.uuid4()
    eval_result = validate_tool_span(
        span_id=span_id,
        kind=SpanKind.TOOL_CALL,
        status=SpanStatus.COMPLETED,
        input_data={"query": "error query"},
        output_data={"status_code": 500, "error": "Internal Server Error"},
        latency_ms=300.0,
    )

    assert eval_result is not None
    assert eval_result.verdict == EvaluationVerdict.FAILURE
    assert eval_result.score == 0.0
    assert eval_result.details["http_status"] == 500


def test_tool_checker_schema_mismatch():
    """Verify tool check fails on schema type mismatch."""
    span_id = uuid.uuid4()
    eval_result = validate_tool_span(
        span_id=span_id,
        kind=SpanKind.TOOL_CALL,
        status=SpanStatus.COMPLETED,
        input_data={"query": 12345, "limit": "invalid_number_string"},
        output_data={"status_code": 200},
        latency_ms=50.0,
        metadata={"expected_schema": {"query": "string", "limit": "integer"}},
    )

    assert eval_result is not None
    assert eval_result.verdict == EvaluationVerdict.FAILURE
    assert eval_result.details["schema_valid"] is False


def test_tool_checker_non_tool_span_skipped():
    """Verify Phase 1 returns None for non-tool spans."""
    span_id = uuid.uuid4()
    eval_result = validate_tool_span(
        span_id=span_id,
        kind=SpanKind.LLM_CALL,
        status=SpanStatus.COMPLETED,
        input_data={"prompt": "hello"},
    )
    assert eval_result is None


# ──────────────────────────────────────────
# Phase 2: Semantic Drift Detector Tests
# ──────────────────────────────────────────

def test_semantic_drift_pass():
    """Verify high semantic alignment produces pass verdict."""
    span_id = uuid.uuid4()
    inp = {"query": "What is the capital of France?", "content": "Information about Paris and France."}
    out = {"summary": "The capital of France is Paris according to the documents."}

    eval_result, embedding = analyze_semantic_drift(
        span_id=span_id,
        kind=SpanKind.LLM_CALL,
        input_data=inp,
        output_data=out,
    )

    assert eval_result is not None
    assert eval_result.phase == EvaluationPhase.SEMANTIC_DRIFT
    assert eval_result.verdict in (EvaluationVerdict.PASS, EvaluationVerdict.WARNING)
    assert eval_result.score is not None and eval_result.score > 0.6
    assert isinstance(embedding, list)
    assert len(embedding) == 384
    assert eval_result.details["drift_threshold"] == 0.70


def test_semantic_drift_hallucination_detected():
    """Verify unrelated output triggers drift / hallucination failure."""
    span_id = uuid.uuid4()
    inp = {"query": "Explain quantum computing algorithms in detail"}
    out = {"summary": "Banana bread recipe requires 3 ripe bananas, flour, sugar, and baking soda."}

    eval_result, embedding = analyze_semantic_drift(
        span_id=span_id,
        kind=SpanKind.LLM_CALL,
        input_data=inp,
        output_data=out,
        threshold=0.70,
    )

    assert eval_result is not None
    assert eval_result.verdict == EvaluationVerdict.FAILURE
    assert eval_result.details["drift_detected"] is True
    assert len(embedding) == 384


def test_embedding_vector_dimensions():
    """Verify generated embedding is exactly 384 dimensions and normalized."""
    vec = generate_embedding("Sample text for vector generation test")
    assert len(vec) == 384
    # Check L2 norm approx 1.0
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 0.05


# ──────────────────────────────────────────
# Phase 3: Judge LLM Tests
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_judge_llm_heuristic_pass():
    """Verify Judge LLM produces a clear non-technical summary and pass verdict for clean step."""
    span_id = uuid.uuid4()
    p1 = validate_tool_span(
        span_id=span_id,
        kind=SpanKind.TOOL_CALL,
        status=SpanStatus.COMPLETED,
        input_data={"query": "test query"},
        output_data={"status_code": 200, "status": "ok"},
    )
    p2, _ = analyze_semantic_drift(
        span_id=span_id,
        kind=SpanKind.PROCESSING,
        input_data={"query": "test query"},
        output_data={"query": "test query"},
    )

    judge_eval = await evaluate_with_llm(
        span_id=span_id,
        name="test_step",
        kind=SpanKind.PROCESSING,
        input_data={"query": "test query"},
        output_data={"status": "ok"},
        latency_ms=45.0,
        phase1_eval=p1,
        phase2_eval=p2,
    )

    assert judge_eval.phase == EvaluationPhase.JUDGE_LLM
    assert judge_eval.verdict == EvaluationVerdict.PASS
    assert judge_eval.summary is not None
    assert len(judge_eval.summary) > 10
    assert "judge_model" in judge_eval.details


@pytest.mark.asyncio
async def test_judge_llm_heuristic_failure_propagation():
    """Verify Judge LLM correctly reports failure when Phase 1 or Phase 2 fails."""
    span_id = uuid.uuid4()
    p1 = validate_tool_span(
        span_id=span_id,
        kind=SpanKind.TOOL_CALL,
        status=SpanStatus.FAILED,
        error_message="Connection timed out to external search API",
    )

    judge_eval = await evaluate_with_llm(
        span_id=span_id,
        name="web_search",
        kind=SpanKind.TOOL_CALL,
        error_message="Connection timed out",
        phase1_eval=p1,
    )

    assert judge_eval.verdict == EvaluationVerdict.FAILURE
    assert judge_eval.score == 0.0
    assert "error" in judge_eval.summary.lower() or "failed" in judge_eval.summary.lower()


# ──────────────────────────────────────────
# Orchestrator & API Integration Tests
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_evaluator_orchestrator_unit():
    """Verify evaluator orchestrator runs Phase 1, Phase 2, and Phase 3 and updates DB."""
    from app.services.evaluator import evaluate_span

    span_id = uuid.uuid4()
    run_id = uuid.uuid4()
    mock_span = TraceSpan(
        id=span_id,
        run_id=run_id,
        name="web_search",
        kind="tool_call",
        status="completed",
        input_data={"query": "AI news", "limit": 5},
        output_data={"status_code": 200, "results": ["article 1", "article 2"]},
        latency_ms=120.0,
        metadata_={"expected_schema": {"query": "string", "limit": "integer"}},
    )

    from unittest.mock import MagicMock

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [
        Evaluation(id=uuid.uuid4(), span_id=span_id, phase="tool_check", verdict="pass", score=1.0),
        Evaluation(id=uuid.uuid4(), span_id=span_id, phase="semantic_drift", verdict="pass", score=0.9),
        Evaluation(id=uuid.uuid4(), span_id=span_id, phase="judge_llm", verdict="pass", score=0.95),
    ]
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    evals = await evaluate_span(mock_span, mock_db)
    assert len(evals) == 3
    assert mock_db.execute.called
    assert mock_db.flush.called


def test_fastapi_evaluations_router():
    """Verify FastAPI evaluations router endpoints are registered properly."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    # Check health
    health_resp = client.get("/api/v1/health")
    assert health_resp.status_code == 200

    # Verify routes registered via OpenAPI specification
    paths = list(app.openapi()["paths"].keys())
    assert "/api/v1/spans/{span_id}/evaluate" in paths
    assert "/api/v1/evaluations" in paths
    assert "/api/v1/runs/{run_id}/evaluate" in paths

