"""The @fathom_trace decorator — core of the Fathom SDK.

Automatically captures function inputs, outputs, execution time, errors,
and parent-child relationships across nested function calls.

Supports both sync and async functions.

Usage:
    from fathom_sdk import FathomClient, fathom_trace

    client = FathomClient(endpoint="http://localhost:8000/api/v1")
    client.start()

    @fathom_trace(client=client, kind="tool_call")
    def web_search(query: str) -> dict:
        return {"results": [...]}

    @fathom_trace(client=client, kind="llm_call", model="gpt-4o")
    async def summarize(text: str) -> str:
        return "summary..."

    # Nested calls automatically form parent → child spans
    @fathom_trace(client=client, kind="processing", name="pipeline")
    def run_pipeline():
        results = web_search("AI news")      # child of pipeline
        summary = summarize(results)          # child of pipeline
        return summary
"""

import functools
import inspect
import logging
import time
import traceback
from uuid import uuid4

from fathom_sdk.client import FathomClient
from fathom_sdk.context import current_run_id, current_span_id
from fathom_sdk.types import SpanData

logger = logging.getLogger("fathom_sdk")


def _safe_serialize(obj, max_depth: int = 5, _depth: int = 0):
    """Convert any object to a JSON-safe representation. Never raises."""
    if _depth > max_depth:
        return str(obj)

    if obj is None or isinstance(obj, (bool, int, float)):
        return obj

    if isinstance(obj, str):
        return obj[:10_000] + "... [truncated]" if len(obj) > 10_000 else obj

    if isinstance(obj, bytes):
        return f"<bytes len={len(obj)}>"

    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v, max_depth, _depth + 1) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set)):
        return [_safe_serialize(item, max_depth, _depth + 1) for item in obj]

    if hasattr(obj, "__dict__"):
        try:
            return {k: _safe_serialize(v, max_depth, _depth + 1) for k, v in obj.__dict__.items() if not k.startswith("_")}
        except Exception:
            return str(obj)

    try:
        return str(obj)
    except Exception:
        return "<unserializable>"


def _capture_inputs(func, args, kwargs) -> dict:
    """Capture function arguments as a JSON-safe dict."""
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return {k: _safe_serialize(v) for k, v in bound.arguments.items()}
    except Exception:
        # Fallback: just capture positional and keyword args
        return {
            "args": [_safe_serialize(a) for a in args],
            "kwargs": {k: _safe_serialize(v) for k, v in kwargs.items()},
        }


def fathom_trace(
    client: FathomClient,
    kind: str = "processing",
    name: str | None = None,
    model: str | None = None,
    metadata: dict | None = None,
    side_effects: str | None = None,
    llm_request: dict | None = None,
):
    """Decorator that traces a function execution as a Fathom span.

    Args:
        client: The FathomClient instance to buffer spans to.
        kind: Span kind — "llm_call", "tool_call", "retrieval", "processing", "agent_decision".
        name: Override for the span name. Defaults to the function name.
        model: Model name for LLM calls (e.g., "gpt-4o").
        metadata: Extra metadata to attach to the span.
        side_effects: Side effects category: "none", "read", "write", "unknown".
        llm_request: Full LLM request params for replay (Section 13.2 R1, 16.1).

    Returns:
        A decorator that wraps the target function.
    """
    from datetime import datetime, timezone

    # Infer default side_effects if not specified
    eff = side_effects
    if eff is None:
        if kind == "retrieval":
            eff = "read"
        elif kind == "processing":
            eff = "none"
        else:
            eff = "unknown"

    def decorator(func):
        span_name = name or func.__name__

        if inspect.iscoroutinefunction(func):
            # ─── ASYNC version ───
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                span_id = uuid4()
                parent_id = current_span_id.get()
                run_id = current_run_id.get()

                token = current_span_id.set(span_id)
                input_data = _capture_inputs(func, args, kwargs)
                started_at = datetime.now(timezone.utc)
                start_time = time.perf_counter()

                # Capture request for LLM replay
                request_payload = llm_request
                if kind == "llm_call" and request_payload is None:
                    request_payload = {
                        "model": model or "gpt-4o-mini",
                        "input": input_data,
                    }

                try:
                    result = await func(*args, **kwargs)
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    ended_at = datetime.now(timezone.utc)

                    span = SpanData(
                        id=span_id,
                        run_id=run_id,
                        parent_span_id=parent_id,
                        name=span_name,
                        kind=kind,
                        status="completed",
                        input_data=input_data,
                        output_data=_safe_serialize(result),
                        latency_ms=round(elapsed_ms, 2),
                        model_name=model,
                        metadata=metadata or {},
                        started_at=started_at,
                        ended_at=ended_at,
                        side_effects=eff,
                        llm_request=request_payload,
                    )
                    client.buffer_span(span)
                    logger.debug("Traced (async) %s [%.1fms]", span_name, elapsed_ms)
                    return result

                except BaseException as e:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    ended_at = datetime.now(timezone.utc)
                    status_val = "cancelled" if isinstance(e, (asyncio.CancelledError, KeyboardInterrupt)) else "failed"

                    span = SpanData(
                        id=span_id,
                        run_id=run_id,
                        parent_span_id=parent_id,
                        name=span_name,
                        kind=kind,
                        status=status_val,
                        input_data=input_data,
                        error_message=traceback.format_exc(),
                        latency_ms=round(elapsed_ms, 2),
                        model_name=model,
                        metadata=metadata or {},
                        started_at=started_at,
                        ended_at=ended_at,
                        side_effects=eff,
                        llm_request=request_payload,
                    )
                    client.buffer_span(span)
                    logger.debug("Traced (async, %s) %s [%.1fms]", status_val, span_name, elapsed_ms)
                    raise  # Transparently re-raise

                finally:
                    current_span_id.reset(token)

            return async_wrapper

        else:
            # ─── SYNC version ───
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                span_id = uuid4()
                parent_id = current_span_id.get()
                run_id = current_run_id.get()

                token = current_span_id.set(span_id)
                input_data = _capture_inputs(func, args, kwargs)
                started_at = datetime.now(timezone.utc)
                start_time = time.perf_counter()

                request_payload = llm_request
                if kind == "llm_call" and request_payload is None:
                    request_payload = {
                        "model": model or "gpt-4o-mini",
                        "input": input_data,
                    }

                try:
                    result = func(*args, **kwargs)
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    ended_at = datetime.now(timezone.utc)

                    span = SpanData(
                        id=span_id,
                        run_id=run_id,
                        parent_span_id=parent_id,
                        name=span_name,
                        kind=kind,
                        status="completed",
                        input_data=input_data,
                        output_data=_safe_serialize(result),
                        latency_ms=round(elapsed_ms, 2),
                        model_name=model,
                        metadata=metadata or {},
                        started_at=started_at,
                        ended_at=ended_at,
                        side_effects=eff,
                        llm_request=request_payload,
                    )
                    client.buffer_span(span)
                    logger.debug("Traced (sync) %s [%.1fms]", span_name, elapsed_ms)
                    return result

                except BaseException as e:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    ended_at = datetime.now(timezone.utc)
                    status_val = "cancelled" if isinstance(e, KeyboardInterrupt) else "failed"

                    span = SpanData(
                        id=span_id,
                        run_id=run_id,
                        parent_span_id=parent_id,
                        name=span_name,
                        kind=kind,
                        status=status_val,
                        input_data=input_data,
                        error_message=traceback.format_exc(),
                        latency_ms=round(elapsed_ms, 2),
                        model_name=model,
                        metadata=metadata or {},
                        started_at=started_at,
                        ended_at=ended_at,
                        side_effects=eff,
                        llm_request=request_payload,
                    )
                    client.buffer_span(span)
                    logger.debug("Traced (sync, %s) %s [%.1fms]", status_val, span_name, elapsed_ms)
                    raise  # Transparently re-raise

                finally:
                    current_span_id.reset(token)

            return sync_wrapper

    return decorator

