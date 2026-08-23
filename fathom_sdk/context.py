"""Context variables for automatic parent-child span tracking.

Uses Python's contextvars module to maintain the current span hierarchy
across nested function calls — even across async boundaries.

How it works:
- When a @fathom_trace decorated function starts, it sets current_span_id
  to its own span ID and saves the reset token.
- Nested decorated functions read current_span_id as their parent_span_id.
- When a function exits, it resets current_span_id back to the parent's value
  using the saved token. This ensures sibling calls don't become children of
  each other.
"""

from contextvars import ContextVar
from uuid import UUID

# The span ID of the currently executing traced function.
# Child spans read this to set their parent_span_id.
current_span_id: ContextVar[UUID | None] = ContextVar("current_span_id", default=None)

# The run ID for the current execution pipeline.
# Set once when a top-level traced function starts.
current_run_id: ContextVar[UUID | None] = ContextVar("current_run_id", default=None)
