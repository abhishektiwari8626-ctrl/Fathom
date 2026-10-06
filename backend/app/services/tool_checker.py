"""Phase 1 — Tool Schema Checker.

Validates spans where kind = "tool_call":
- Validates input format / parameters against expected schema
- Verifies HTTP status codes and response success
- Flags failed status or exception messages
- Generates structured EvaluationCreate records matching ARCHITECTURE.md Section 5 & 9

Owner: Abhishek
"""

from typing import Any
from uuid import UUID

from app.enums import EvaluationPhase, EvaluationVerdict, SpanKind, SpanStatus
from app.schemas import EvaluationCreate


def _infer_type_name(val: Any) -> str:
    """Return JSON schema primitive type name for a python value."""
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "number"
    if isinstance(val, str):
        return "string"
    if isinstance(val, list):
        return "array"
    if isinstance(val, dict):
        return "object"
    if val is None:
        return "null"
    return type(val).__name__


def _extract_http_status(metadata: dict, output_data: dict, error_message: str | None, status: str) -> int:
    """Extract or infer HTTP status code from span data."""
    # Check explicit status code in metadata or output
    for container in (metadata, output_data):
        if isinstance(container, dict):
            for key in ("status_code", "http_status", "statusCode", "status"):
                val = container.get(key)
                if isinstance(val, int) and 100 <= val <= 599:
                    return val
                if isinstance(val, str) and val.isdigit() and 100 <= int(val) <= 599:
                    return int(val)

    # Check for known status text
    if isinstance(output_data, dict):
        status_text = str(output_data.get("status", "")).lower()
        if status_text in ("ok", "success", "sent", "delivered", "completed", "200"):
            return 200
        if status_text in ("not_found", "404"):
            return 404
        if status_text in ("bad_request", "invalid", "400"):
            return 400
        if status_text in ("error", "failed", "500", "internal_error"):
            return 500

    # If span status is failed or has error message, default to 500 or 400
    if status == SpanStatus.FAILED.value or status == SpanStatus.FAILED or error_message:
        return 500

    return 200


def validate_tool_span(
    span_id: UUID,
    kind: str | SpanKind,
    status: str | SpanStatus,
    input_data: dict | None = None,
    output_data: dict | None = None,
    error_message: str | None = None,
    latency_ms: float = 0.0,
    metadata: dict | None = None,
) -> EvaluationCreate | None:
    """Evaluate a tool_call span for schema correctness and execution status.

    Args:
        span_id: UUID of the target span.
        kind: SpanKind of the span (only TOOL_CALL is evaluated in Phase 1).
        status: SpanStatus (completed, failed, etc.).
        input_data: Input payload dictionary.
        output_data: Output payload dictionary.
        error_message: Optional error/traceback string.
        latency_ms: Execution time in milliseconds.
        metadata: User/system metadata.

    Returns:
        EvaluationCreate with phase=EvaluationPhase.TOOL_CHECK, or None if kind != tool_call.
    """
    kind_val = kind.value if isinstance(kind, SpanKind) else str(kind)
    status_val = status.value if isinstance(status, SpanStatus) else str(status)

    if kind_val != SpanKind.TOOL_CALL.value and kind_val != "tool_call":
        # Phase 1 is specifically for tool_call spans
        return None

    input_payload = input_data if isinstance(input_data, dict) else {}
    output_payload = output_data if isinstance(output_data, dict) else {}
    meta = metadata if isinstance(metadata, dict) else {}

    # Expected schema derived from declared schema in metadata or inferred from input parameters
    expected_schema: dict[str, str] = {}
    if "expected_schema" in meta and isinstance(meta["expected_schema"], dict):
        expected_schema = {str(k): str(v) for k, v in meta["expected_schema"].items()}
    else:
        for k, v in input_payload.items():
            expected_schema[str(k)] = _infer_type_name(v)

    # Validate actual payload against expected types if explicit schema provided
    schema_valid = True
    if "expected_schema" in meta and isinstance(meta["expected_schema"], dict):
        for param, expected_type in meta["expected_schema"].items():
            if param not in input_payload:
                schema_valid = False
                break
            actual_type = _infer_type_name(input_payload[param])
            if expected_type in ("integer", "number") and actual_type in ("integer", "number"):
                continue
            if actual_type != expected_type:
                schema_valid = False
                break

    http_status = _extract_http_status(meta, output_payload, error_message, status_val)

    # Check for empty results (Section 15.2)
    has_empty_results = False
    if not output_payload:
        has_empty_results = True
    elif isinstance(output_payload, dict):
        for key in ("results", "data", "items", "rows"):
            if key in output_payload and isinstance(output_payload[key], list) and len(output_payload[key]) == 0:
                has_empty_results = True
                break

    # Determine verdict and score
    is_failed = (
        status_val == SpanStatus.FAILED.value
        or status_val == "failed"
        or error_message is not None
        or http_status >= 400
        or not schema_valid
    )

    error_category = None
    is_retryable = False

    if is_failed:
        verdict = EvaluationVerdict.FAILURE
        score = 0.0
        if 400 <= http_status < 500:
            error_category = "caller_error"
            if http_status == 429:
                is_retryable = True
        elif http_status >= 500:
            error_category = "provider_error"
            if http_status in (502, 503, 504):
                is_retryable = True
    elif http_status >= 300 or has_empty_results:
        verdict = EvaluationVerdict.WARNING
        score = 0.6
    else:
        verdict = EvaluationVerdict.PASS
        score = 1.0

    details = {
        "expected_schema": expected_schema,
        "actual_payload": input_payload,
        "schema_valid": schema_valid,
        "http_status": http_status,
        "response_time_ms": round(float(latency_ms), 2),
        "error_category": error_category,
        "is_retryable": is_retryable,
        "has_empty_results": has_empty_results,
    }

    if verdict == EvaluationVerdict.FAILURE:
        summary = f"Tool call failed with HTTP {http_status} ({error_category or 'execution failure'}): {error_message or 'Schema validation error or API error'}"
    elif has_empty_results:
        summary = f"Tool call succeeded with HTTP {http_status} but returned zero results."
    elif verdict == EvaluationVerdict.WARNING:
        summary = f"Tool call returned HTTP {http_status} with warnings."
    else:
        summary = f"Tool call completed cleanly with HTTP {http_status} ({latency_ms:.1f}ms)."

    return EvaluationCreate(
        span_id=span_id,
        phase=EvaluationPhase.TOOL_CHECK,
        verdict=verdict,
        score=score,
        details=details,
        summary=summary,
    )
