"""Fathom SDK — Causal tracing for multi-step AI agents.

Usage:
    from fathom_sdk import FathomClient, fathom_trace

    client = FathomClient(endpoint="http://localhost:8000/api/v1")
    client.start()

    @fathom_trace(client=client, kind="llm_call", model="gpt-4o")
    def my_llm_step(prompt: str) -> str:
        ...
"""

from fathom_sdk.client import FathomClient
from fathom_sdk.context import current_run_id, current_span_id
from fathom_sdk.tracer import fathom_trace
from fathom_sdk.types import SpanData

__all__ = [
    "FathomClient",
    "fathom_trace",
    "current_run_id",
    "current_span_id",
    "SpanData",
]
