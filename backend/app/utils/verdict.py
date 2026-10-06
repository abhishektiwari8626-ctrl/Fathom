"""Verdict precedence computation for Fathom spans (Section 15.4).

A span can carry up to three evaluations (tool_check, semantic_drift, judge_llm)
that may disagree. This utility computes one effective verdict so that UI display,
alerting, and graph navigation remain consistent.
"""

from typing import Iterable, Any
from app.enums import EvaluationPhase, EvaluationVerdict


def compute_effective_verdict(evaluations: Iterable[Any]) -> EvaluationVerdict:
    """Compute the single effective verdict from all evaluations on a span.

    Evaluated top to bottom per Section 15.4:
      1. Phase 1 = failure -> failure (deterministic; never overridden by the judge).
      2. Phase 3 = failure -> failure.
      3. Phase 3 = error (judge unavailable) -> Worst of Phase 1 / Phase 2.
      4. Phase 3 = pass and Phase 2 = failure -> warning (embedding signal not confirmed by judge).
      5. Phase 3 = warning -> warning.
      6. Otherwise -> pass (or worst available if no Phase 3 exists).
    """
    phase_verdicts: dict[str, EvaluationVerdict] = {}

    for ev in evaluations:
        phase = ev.phase.value if hasattr(ev.phase, "value") else str(ev.phase)
        verdict = ev.verdict if isinstance(ev.verdict, EvaluationVerdict) else EvaluationVerdict(ev.verdict)
        phase_verdicts[phase] = verdict

    p1 = phase_verdicts.get(EvaluationPhase.TOOL_CHECK.value)
    p2 = phase_verdicts.get(EvaluationPhase.SEMANTIC_DRIFT.value)
    p3 = phase_verdicts.get(EvaluationPhase.JUDGE_LLM.value)

    # 1. Phase 1 = failure -> failure (deterministic; never overridden by the judge)
    if p1 == EvaluationVerdict.FAILURE:
        return EvaluationVerdict.FAILURE

    # 2. Phase 3 = failure -> failure
    if p3 == EvaluationVerdict.FAILURE:
        return EvaluationVerdict.FAILURE

    # 3. Phase 3 = error (judge unavailable) -> Worst of Phase 1 / Phase 2
    if p3 == EvaluationVerdict.ERROR:
        if p1 == EvaluationVerdict.FAILURE or p2 == EvaluationVerdict.FAILURE:
            return EvaluationVerdict.FAILURE
        if p1 == EvaluationVerdict.WARNING or p2 == EvaluationVerdict.WARNING:
            return EvaluationVerdict.WARNING
        return EvaluationVerdict.ERROR

    # 4. Phase 3 = pass and Phase 2 = failure -> warning (embedding signal not confirmed by judge)
    if p3 == EvaluationVerdict.PASS and p2 == EvaluationVerdict.FAILURE:
        return EvaluationVerdict.WARNING

    # 5. Phase 3 = warning -> warning
    if p3 == EvaluationVerdict.WARNING:
        return EvaluationVerdict.WARNING

    # If Judge LLM passed cleanly and no earlier failure
    if p3 == EvaluationVerdict.PASS:
        if p2 == EvaluationVerdict.WARNING or p1 == EvaluationVerdict.WARNING:
            return EvaluationVerdict.WARNING
        return EvaluationVerdict.PASS

    # If Judge didn't run: fallback to Phase 1 / Phase 2
    if p2 == EvaluationVerdict.FAILURE or p1 == EvaluationVerdict.FAILURE:
        return EvaluationVerdict.FAILURE
    if p2 == EvaluationVerdict.WARNING or p1 == EvaluationVerdict.WARNING:
        return EvaluationVerdict.WARNING

    return EvaluationVerdict.PASS
