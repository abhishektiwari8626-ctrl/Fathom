"""SDK-side type definitions for span data."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class SpanData:
    """Represents a captured span before it's sent to the Fathom backend.

    This is the internal SDK representation. It gets converted to the
    SpanCreate Pydantic schema before being sent over HTTP.
    """

    id: UUID
    run_id: UUID
    parent_span_id: UUID | None
    name: str
    kind: str
    status: str
    input_data: dict = field(default_factory=dict)
    output_data: dict = field(default_factory=dict)
    error_message: str | None = None
    latency_ms: float = 0.0
    token_count: int = 0
    model_name: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    side_effects: str = "unknown"
    llm_request: dict | None = None
    cost_usd: float | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict:
        """Convert to a dict matching the SpanCreate API schema."""
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "parent_span_id": str(self.parent_span_id) if self.parent_span_id else None,
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error_message": self.error_message,
            "latency_ms": self.latency_ms,
            "token_count": self.token_count,
            "model_name": self.model_name,
            "metadata": self.metadata,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "side_effects": self.side_effects,
            "llm_request": self.llm_request,
            "cost_usd": self.cost_usd,
        }

