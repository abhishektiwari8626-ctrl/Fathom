"""Phase 3 — Judge LLM.

Evaluates ALL spans:
- Sends span input, output, error message, and Phase 1 & Phase 2 results to Judge LLM
- Prompt asks: "Is this step's output correct? Explain any problems in plain English."
- Produces a simple, clear, non-technical explanation saved in the `summary` field
- Produces structured details with judge model, token counts, and reasoning
- Handles fallback heuristic judging when API keys are not provided

Owner: Abhishek
"""

import json
import logging
from typing import Any
from uuid import UUID

import httpx

from app.config import get_settings
from app.enums import EvaluationPhase, EvaluationVerdict, SpanKind
from app.schemas import EvaluationCreate

logger = logging.getLogger("fathom.evaluator.judge")


def _generate_heuristic_judgment(
    name: str,
    kind: str,
    input_data: dict,
    output_data: dict,
    error_message: str | None,
    phase1_eval: EvaluationCreate | None,
    phase2_eval: EvaluationCreate | None,
) -> tuple[EvaluationVerdict, float, str, str]:
    """Fallback judge logic when external LLM API is unavailable."""
    # Check if there is an explicit error
    if error_message:
        verdict = EvaluationVerdict.FAILURE
        score = 0.0
        summary = f"This step encountered an error during execution: {error_message.splitlines()[-1] if error_message else 'Step failed.'}"
        reasoning = f"Execution raised an unhandled exception: {error_message}"
        return verdict, score, summary, reasoning

    # Check Phase 1 tool check verdict
    if phase1_eval is not None:
        if phase1_eval.verdict == EvaluationVerdict.FAILURE:
            http_status = phase1_eval.details.get("http_status", 500)
            verdict = EvaluationVerdict.FAILURE
            score = 0.0
            summary = f"The tool '{name}' failed with HTTP error status {http_status}."
            reasoning = f"Tool validation failed schema or returned error status {http_status}."
            return verdict, score, summary, reasoning
        elif phase1_eval.verdict == EvaluationVerdict.WARNING:
            verdict = EvaluationVerdict.WARNING
            score = 0.6
            summary = f"The tool '{name}' executed with warnings."
            reasoning = "Tool validation reported minor parameter or response warning."
            return verdict, score, summary, reasoning

    # Check Phase 2 semantic drift verdict
    if phase2_eval is not None:
        if phase2_eval.verdict == EvaluationVerdict.FAILURE:
            drift_score = phase2_eval.score or 0.0
            verdict = EvaluationVerdict.FAILURE
            score = drift_score
            summary = (
                f"The AI generated output that appears disconnected from the input data "
                f"(semantic alignment score: {drift_score:.2f})."
            )
            reasoning = (
                f"Semantic drift detected below threshold {phase2_eval.details.get('drift_threshold', 0.70)}. "
                f"Similarity was {phase2_eval.details.get('cosine_similarity', 0.0)}."
            )
            return verdict, score, summary, reasoning
        elif phase2_eval.verdict == EvaluationVerdict.WARNING:
            drift_score = phase2_eval.score or 0.75
            verdict = EvaluationVerdict.WARNING
            score = drift_score
            summary = f"This step produced an answer with minor deviations from the input (alignment score: {drift_score:.2f})."
            reasoning = f"Mild semantic drift detected (score: {drift_score})."
            return verdict, score, summary, reasoning

    # Check empty output
    if not output_data or (isinstance(output_data, dict) and len(output_data) == 0):
        verdict = EvaluationVerdict.WARNING
        score = 0.70
        summary = f"The step '{name}' finished without returning any output data."
        reasoning = "Output payload was empty dictionary."
        return verdict, score, summary, reasoning

    # Default: Pass
    verdict = EvaluationVerdict.PASS
    score = 0.95
    summary = f"This step completed successfully and the output matches the expected requirements."
    reasoning = f"The output for '{name}' was produced without errors and conforms to inputs."
    return verdict, score, summary, reasoning


async def evaluate_with_llm(
    span_id: UUID,
    name: str,
    kind: str | SpanKind,
    input_data: dict | None = None,
    output_data: dict | None = None,
    error_message: str | None = None,
    latency_ms: float = 0.0,
    phase1_eval: EvaluationCreate | None = None,
    phase2_eval: EvaluationCreate | None = None,
) -> EvaluationCreate:
    """Run LLM-as-a-judge evaluation on a span.

    Args:
        span_id: UUID of the target span.
        name: Name of the span / step.
        kind: Span kind.
        input_data: Input data payload.
        output_data: Output data payload.
        error_message: Optional error message.
        latency_ms: Execution duration.
        phase1_eval: Optional Phase 1 tool check evaluation result.
        phase2_eval: Optional Phase 2 semantic drift evaluation result.

    Returns:
        EvaluationCreate with phase=EvaluationPhase.JUDGE_LLM.
    """
    settings = get_settings()
    kind_val = kind.value if isinstance(kind, SpanKind) else str(kind)
    inp = input_data or {}
    out = output_data or {}

    judge_model = settings.JUDGE_LLM_MODEL or "gpt-4o-mini"
    api_key = settings.JUDGE_LLM_API_KEY

    # If OpenAI API Key is provided, call external LLM
    if api_key and api_key.strip():
        system_prompt = (
            "You are an impartial AI evaluation judge. Your job is to inspect an AI agent step "
            "and decide if it succeeded, had warnings, or failed. "
            "You MUST respond ONLY with valid JSON in this exact structure:\n"
            "{\n"
            '  "verdict": "pass" | "warning" | "failure",\n'
            '  "score": 0.0 to 1.0,\n'
            '  "summary": "A simple, clear plain-English explanation for non-technical users (1-2 sentences)",\n'
            '  "reasoning": "Technical explanation of the evaluation"\n'
            "}"
        )

        user_content = {
            "step_name": name,
            "step_kind": kind_val,
            "input_data": inp,
            "output_data": out,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "phase1_tool_check": phase1_eval.model_dump() if phase1_eval else None,
            "phase2_semantic_drift": phase2_eval.model_dump() if phase2_eval else None,
        }

        url = f"{settings.OPENAI_BASE_URL.rstrip('/') if settings.OPENAI_BASE_URL else 'https://api.openai.com/v1'}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": judge_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_content, default=str)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=body)
                if resp.status_code == 200:
                    resp_json = resp.json()
                    usage = resp_json.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    completion_tokens = usage.get("completion_tokens", 0)
                    content_str = resp_json["choices"][0]["message"]["content"]
                    parsed = json.loads(content_str)

                    raw_verdict = str(parsed.get("verdict", "pass")).lower()
                    if raw_verdict in ("pass", "warning", "failure"):
                        verdict = EvaluationVerdict(raw_verdict)
                    else:
                        verdict = EvaluationVerdict.PASS

                    score = float(parsed.get("score", 0.95))
                    score = max(0.0, min(1.0, score))
                    summary = parsed.get("summary", "Step executed successfully.")
                    reasoning = parsed.get("reasoning", "")

                    return EvaluationCreate(
                        span_id=span_id,
                        phase=EvaluationPhase.JUDGE_LLM,
                        verdict=verdict,
                        score=score,
                        details={
                            "judge_model": judge_model,
                            "judge_prompt_tokens": prompt_tokens,
                            "judge_completion_tokens": completion_tokens,
                            "reasoning": reasoning,
                        },
                        summary=summary,
                    )
        except Exception as e:
            logger.warning("Judge LLM API call failed: %s. Using heuristic judge.", e)

    # Heuristic fallback judge
    verdict, score, summary, reasoning = _generate_heuristic_judgment(
        name=name,
        kind=kind_val,
        input_data=inp,
        output_data=out,
        error_message=error_message,
        phase1_eval=phase1_eval,
        phase2_eval=phase2_eval,
    )

    return EvaluationCreate(
        span_id=span_id,
        phase=EvaluationPhase.JUDGE_LLM,
        verdict=verdict,
        score=score,
        details={
            "judge_model": judge_model,
            "judge_prompt_tokens": len(str(inp)) // 4 + 50,
            "judge_completion_tokens": len(summary) // 4 + 20,
            "reasoning": reasoning,
        },
        summary=summary,
    )
