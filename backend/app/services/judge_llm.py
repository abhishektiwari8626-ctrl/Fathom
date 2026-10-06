"""Phase 3 — Judge LLM.

Evaluates ALL spans:
- Sends span input, output, error message, and Phase 1 & Phase 2 results to Judge LLM
- Prompt asks: "Is this step's output correct? Explain any problems in plain English."
- Produces a simple, clear, non-technical explanation saved in the `summary` field
- Produces structured details with judge model, token counts, and reasoning
- Handles fallback heuristic judging when API keys are not provided

Owner: Abhishek
"""

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

import httpx

from app.config import get_settings
from app.enums import EvaluationPhase, EvaluationVerdict, SpanKind
from app.schemas import EvaluationCreate

logger = logging.getLogger("fathom.evaluator.judge")

JUDGE_PROMPT_TEMPLATE = (
    "You are an impartial AI evaluation judge. Your job is to inspect an AI agent step "
    "and decide if it succeeded, had warnings, or failed.\n"
    "You MUST respond ONLY with valid JSON in this exact structure:\n"
    "{\n"
    '  "verdict": "pass" | "warning" | "failure",\n'
    '  "score": 0.0 to 1.0,\n'
    '  "summary": "What happened in plain English for non-technical users (1-2 sentences)",\n'
    '  "reasoning": "Why it matters: technical rationale and causal impact",\n'
    '  "suggested_fix": "Actionable instructions on how to fix this step if needed"\n'
    "}"
)

EVALUATOR_VERSION = "1.0.0"


def _prompt_hash() -> str:
    return hashlib.sha256(JUDGE_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()


def _generate_heuristic_judgment(
    name: str,
    kind: str,
    input_data: dict,
    output_data: dict,
    error_message: str | None,
    phase1_eval: EvaluationCreate | None,
    phase2_eval: EvaluationCreate | None,
) -> tuple[EvaluationVerdict, float, str, str, str | None]:
    """Fallback judge logic when external LLM API is unavailable.

    Returns:
        (verdict, score, summary [what happened], reasoning [why it matters], suggested_fix)
    """
    # Check if there is an explicit error
    if error_message:
        verdict = EvaluationVerdict.FAILURE
        score = 0.0
        summary = f"This step encountered an error during execution: {error_message.splitlines()[-1] if error_message else 'Step failed.'}"
        reasoning = f"Execution raised an unhandled exception: {error_message}"
        suggested_fix = "Review stack trace and handle exception or validate input parameters before execution."
        return verdict, score, summary, reasoning, suggested_fix

    # Check Phase 1 tool check verdict
    if phase1_eval is not None:
        if phase1_eval.verdict == EvaluationVerdict.FAILURE:
            http_status = phase1_eval.details.get("http_status", 500)
            verdict = EvaluationVerdict.FAILURE
            score = 0.0
            summary = f"The tool '{name}' failed with HTTP error status {http_status}."
            reasoning = f"Tool validation failed schema or returned error status {http_status}."
            suggested_fix = "Verify tool input parameters match the schema and external API endpoint is accessible."
            return verdict, score, summary, reasoning, suggested_fix
        elif phase1_eval.verdict == EvaluationVerdict.WARNING:
            verdict = EvaluationVerdict.WARNING
            score = 0.6
            summary = f"The tool '{name}' executed with warnings."
            reasoning = "Tool validation reported empty result or minor parameter issue."
            suggested_fix = "Ensure search or query parameters are broad enough to return results."
            return verdict, score, summary, reasoning, suggested_fix

    # Check Phase 2 semantic drift verdict
    if phase2_eval is not None:
        if phase2_eval.verdict == EvaluationVerdict.FAILURE:
            drift_score = phase2_eval.score or 0.0
            verdict = EvaluationVerdict.FAILURE
            score = drift_score
            summary = (
                f"The AI generated output that appears disconnected from the input goal "
                f"(semantic alignment score: {drift_score:.2f})."
            )
            reasoning = (
                f"Semantic drift detected below threshold {phase2_eval.details.get('drift_threshold', 0.70)}. "
                f"Similarity was {phase2_eval.details.get('cosine_similarity', 0.0)}."
            )
            suggested_fix = "Tighten prompt constraints and specify explicit output format to prevent hallucination."
            return verdict, score, summary, reasoning, suggested_fix
        elif phase2_eval.verdict == EvaluationVerdict.WARNING:
            drift_score = phase2_eval.score or 0.75
            verdict = EvaluationVerdict.WARNING
            score = drift_score
            summary = f"This step produced an answer with minor deviations from the input (alignment score: {drift_score:.2f})."
            reasoning = f"Mild semantic drift detected (score: {drift_score}). Output may be overly concise."
            suggested_fix = "Provide clearer context in the prompt to keep the model focused on the objective."
            return verdict, score, summary, reasoning, suggested_fix

    # Check empty output
    if not output_data or (isinstance(output_data, dict) and len(output_data) == 0):
        verdict = EvaluationVerdict.WARNING
        score = 0.70
        summary = f"The step '{name}' finished without returning any output data."
        reasoning = "Output payload was empty dictionary."
        suggested_fix = "Check data source or ensure the operation returns a structured non-empty payload."
        return verdict, score, summary, reasoning, suggested_fix

    # Default: Pass
    verdict = EvaluationVerdict.PASS
    score = 0.95
    summary = f"This step completed successfully and the output matches the expected requirements."
    reasoning = f"The output for '{name}' was produced without errors and conforms to inputs."
    suggested_fix = None
    return verdict, score, summary, reasoning, suggested_fix


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
    """Run LLM-as-a-judge evaluation on a span with full metadata recording."""
    settings = get_settings()
    kind_val = kind.value if isinstance(kind, SpanKind) else str(kind)
    inp = input_data or {}
    out = output_data or {}

    judge_model = settings.JUDGE_LLM_MODEL or "gpt-4o-mini"
    api_key = settings.JUDGE_LLM_API_KEY
    current_prompt_hash = _prompt_hash()

    # If OpenAI API Key is provided, call external LLM
    if api_key and api_key.strip():
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
                {"role": "system", "content": JUDGE_PROMPT_TEMPLATE},
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
                    if raw_verdict in ("pass", "warning", "failure", "error"):
                        verdict = EvaluationVerdict(raw_verdict)
                    else:
                        verdict = EvaluationVerdict.PASS

                    score = float(parsed.get("score", 0.95))
                    score = max(0.0, min(1.0, score))
                    summary = parsed.get("summary", "Step executed successfully.")
                    reasoning = parsed.get("reasoning", "")
                    suggested_fix = parsed.get("suggested_fix")

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
                            "suggested_fix": suggested_fix,
                        },
                        summary=summary,
                        evaluator_version=EVALUATOR_VERSION,
                        evaluator_model=judge_model,
                        prompt_hash=current_prompt_hash,
                    )
                else:
                    err_msg = f"Judge API returned HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning("Judge LLM error: %s", err_msg)
                    return EvaluationCreate(
                        span_id=span_id,
                        phase=EvaluationPhase.JUDGE_LLM,
                        verdict=EvaluationVerdict.ERROR,
                        score=0.0,
                        details={"error": err_msg},
                        summary="Judge evaluation encountered an HTTP error.",
                        evaluator_version=EVALUATOR_VERSION,
                        evaluator_model=judge_model,
                        prompt_hash=current_prompt_hash,
                        error_message=err_msg,
                    )
        except Exception as e:
            err_msg = f"Judge LLM API call failed: {e}"
            logger.warning(err_msg)
            # Evaluator failure is recorded as ERROR verdict (Section 15.5)
            return EvaluationCreate(
                span_id=span_id,
                phase=EvaluationPhase.JUDGE_LLM,
                verdict=EvaluationVerdict.ERROR,
                score=0.0,
                details={"error": str(e)},
                summary="Judge evaluation encountered an unexpected exception.",
                evaluator_version=EVALUATOR_VERSION,
                evaluator_model=judge_model,
                prompt_hash=current_prompt_hash,
                error_message=str(e),
            )

    # Heuristic fallback judge when no API key configured
    verdict, score, summary, reasoning, suggested_fix = _generate_heuristic_judgment(
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
            "judge_model": f"{judge_model} (heuristic fallback)",
            "judge_prompt_tokens": len(str(inp)) // 4 + 50,
            "judge_completion_tokens": len(summary) // 4 + 20,
            "reasoning": reasoning,
            "suggested_fix": suggested_fix,
        },
        summary=summary,
        evaluator_version=EVALUATOR_VERSION,
        evaluator_model=judge_model,
        prompt_hash=current_prompt_hash,
    )

