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
):
    """Decorator that traces a function execution as a Fathom span.

    Args:
        client: The FathomClient instance to buffer spans to.
        kind: Span kind — "llm_call", "tool_call", "retrieval", "processing", "agent_decision".
        name: Override for the span name. Defaults to the function name.
        model: Model name for LLM calls (e.g., "gpt-4o").
        metadata: Extra metadata to attach to the span.

    Returns:
        A decorator that wraps the target function.
    """

    def decorator(func):
        span_name = name or func.__name__

        if inspect.iscoroutinefunction(func):
            # ─── ASYNC version ───
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                span_id = uuid4()
                parent_id = current_span_id.get()
                run_id = current_run_id.get()

                # Set this span as the current span for child calls
                token = current_span_id.set(span_id)

                input_data = _capture_inputs(func, args, kwargs)
                start_time = time.perf_counter()

                try:
                    result = await func(*args, **kwargs)
                    elapsed_ms = (time.perf_counter() - start_time) * 1000

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
                    )
                    client.buffer_span(span)
                    logger.debug("Traced (async) %s [%.1fms]", span_name, elapsed_ms)

                    return result

                except Exception as e:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000

                    span = SpanData(
                        id=span_id,
                        run_id=run_id,
                        parent_span_id=parent_id,
                        name=span_name,
                        kind=kind,
                        status="failed",
                        input_data=input_data,
                        error_message=traceback.format_exc(),
                        latency_ms=round(elapsed_ms, 2),
                        model_name=model,
                        metadata=metadata or {},
                    )
                    client.buffer_span(span)
                    logger.debug("Traced (async, FAILED) %s [%.1fms]", span_name, elapsed_ms)

                    raise  # Re-raise — decorator must be transparent

                finally:
                    # CRITICAL: Reset contextvar to parent's value.
                    # Without this, sibling calls would incorrectly become children.
                    current_span_id.reset(token)

            return async_wrapper

        else:
            # ─── SYNC version ───
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                span_id = uuid4()
                parent_id = current_span_id.get()
                run_id = current_run_id.get()

                # Set this span as the current span for child calls
                token = current_span_id.set(span_id)

                input_data = _capture_inputs(func, args, kwargs)
                start_time = time.perf_counter()

                try:
                    result = func(*args, **kwargs)
                    elapsed_ms = (time.perf_counter() - start_time) * 1000

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
                    )
                    client.buffer_span(span)
                    logger.debug("Traced (sync) %s [%.1fms]", span_name, elapsed_ms)

                    return result

                except Exception as e:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000

                    span = SpanData(
                        id=span_id,
                        run_id=run_id,
                        parent_span_id=parent_id,
                        name=span_name,
                        kind=kind,
                        status="failed",
                        input_data=input_data,
                        error_message=traceback.format_exc(),
                        latency_ms=round(elapsed_ms, 2),
                        model_name=model,
                        metadata=metadata or {},
                    )
                    client.buffer_span(span)
                    logger.debug("Traced (sync, FAILED) %s [%.1fms]", span_name, elapsed_ms)

                    raise  # Re-raise — decorator must be transparent

                finally:
                    # CRITICAL: Reset contextvar to parent's value.
                    current_span_id.reset(token)

            return sync_wrapper

    return decorator
