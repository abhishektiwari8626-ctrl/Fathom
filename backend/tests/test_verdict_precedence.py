"""Unit tests for verdict precedence (Section 15.4, Task 0.6)."""

from datetime import datetime, timezone
from uuid import uuid4
import pytest

from app.enums import EvaluationPhase, EvaluationVerdict
from app.schemas import EvaluationResponse
from app.utils.verdict import compute_effective_verdict


def _make_eval(phase: EvaluationPhase, verdict: EvaluationVerdict) -> EvaluationResponse:
    return EvaluationResponse(
        id=uuid4(),
        span_id=uuid4(),
        phase=phase,
        verdict=verdict,
        score=1.0 if verdict == EvaluationVerdict.PASS else 0.0,
        details={},
        summary="Test evaluation",
        created_at=datetime.now(timezone.utc),
    )


def test_phase1_failure_never_overridden_by_judge():
    """Rule 1: Phase 1 failure is deterministic and can never be downgraded by the judge."""
    p1 = _make_eval(EvaluationPhase.TOOL_CHECK, EvaluationVerdict.FAILURE)
    p3 = _make_eval(EvaluationPhase.JUDGE_LLM, EvaluationVerdict.PASS)
    assert compute_effective_verdict([p1, p3]) == EvaluationVerdict.FAILURE


def test_phase3_failure_is_effective_failure():
    """Rule 2: Phase 3 failure results in failure."""
    p2 = _make_eval(EvaluationPhase.SEMANTIC_DRIFT, EvaluationVerdict.PASS)
    p3 = _make_eval(EvaluationPhase.JUDGE_LLM, EvaluationVerdict.FAILURE)
    assert compute_effective_verdict([p2, p3]) == EvaluationVerdict.FAILURE


def test_phase3_error_falls_back_to_worst_previous():
    """Rule 3: Phase 3 error (judge unavailable) falls back to worst of Phase 1 / Phase 2."""
    p2 = _make_eval(EvaluationPhase.SEMANTIC_DRIFT, EvaluationVerdict.WARNING)
    p3 = _make_eval(EvaluationPhase.JUDGE_LLM, EvaluationVerdict.ERROR)
    assert compute_effective_verdict([p2, p3]) == EvaluationVerdict.WARNING

    p1 = _make_eval(EvaluationPhase.TOOL_CHECK, EvaluationVerdict.FAILURE)
    assert compute_effective_verdict([p1, p3]) == EvaluationVerdict.FAILURE


def test_phase3_pass_and_phase2_failure_is_warning():
    """Rule 4: Phase 3 pass but Phase 2 failure results in warning (judge didn't confirm embedding drift)."""
    p2 = _make_eval(EvaluationPhase.SEMANTIC_DRIFT, EvaluationVerdict.FAILURE)
    p3 = _make_eval(EvaluationPhase.JUDGE_LLM, EvaluationVerdict.PASS)
    assert compute_effective_verdict([p2, p3]) == EvaluationVerdict.WARNING


def test_phase3_warning_is_warning():
    """Rule 5: Phase 3 warning results in warning."""
    p2 = _make_eval(EvaluationPhase.SEMANTIC_DRIFT, EvaluationVerdict.PASS)
    p3 = _make_eval(EvaluationPhase.JUDGE_LLM, EvaluationVerdict.WARNING)
    assert compute_effective_verdict([p2, p3]) == EvaluationVerdict.WARNING


def test_all_pass_is_pass():
    """Rule 6: If all pass, effective verdict is pass."""
    p1 = _make_eval(EvaluationPhase.TOOL_CHECK, EvaluationVerdict.PASS)
    p3 = _make_eval(EvaluationPhase.JUDGE_LLM, EvaluationVerdict.PASS)
    assert compute_effective_verdict([p1, p3]) == EvaluationVerdict.PASS
