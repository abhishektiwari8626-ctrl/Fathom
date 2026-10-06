"""SQLAlchemy ORM models for trace_runs, trace_spans, and evaluations.

Schema contracts are defined in ARCHITECTURE.md Section 5.
All team members depend on these models — do NOT modify without team approval.
"""

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    """Generate a new UUID4."""
    return uuid.uuid4()


class TraceRun(Base):
    """A single execution run of an AI agent pipeline.

    One run contains many spans (steps). This is the top-level grouping.
    """

    __tablename__ = "trace_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="running")
    total_tokens = Column(Integer, default=0)
    total_latency_ms = Column(Float, default=0.0)
    metadata_ = Column("metadata", JSONB, default=dict)
    has_rewinds = Column(Boolean, nullable=False, default=False)
    active_group_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    spans = relationship("TraceSpan", back_populates="run", cascade="all, delete-orphan")
    links = relationship("SpanLink", back_populates="run", cascade="all, delete-orphan")


class TraceSpan(Base):
    """A single step/operation within a trace run.

    Spans form a DAG via parent_span_id and span_links.
    Root spans have parent_span_id = NULL.

    The embedding column (384-dim vector) is written by the evaluation engine,
    NOT by the ingestion API. It is nullable on insert.
    """

    __tablename__ = "trace_spans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trace_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Dropped hard FK constraint to allow out-of-order ingestion (S-01), index preserved
    parent_span_id = Column(UUID(as_uuid=True), nullable=True)
    name = Column(String(255), nullable=False)
    kind = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default="running")
    input_data = Column(JSONB, default=dict)
    output_data = Column(JSONB, default=dict)
    error_message = Column(Text, nullable=True)
    latency_ms = Column(Float, nullable=False, default=0.0)
    token_count = Column(Integer, default=0)
    model_name = Column(String(100), nullable=True)
    embedding = Column(Vector(384), nullable=True)
    metadata_ = Column("metadata", JSONB, default=dict)

    # Ordering & timing for waterfall views (R3)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # For time-travel rewind (Section 8 & 13.3)
    rewind_group_id = Column(UUID(as_uuid=True), nullable=True)
    rewind_depth = Column(Integer, default=0)
    origin_span_id = Column(UUID(as_uuid=True), nullable=True)
    side_effects = Column(String(10), nullable=False, default="unknown")  # none | read | write | unknown
    llm_request = Column(JSONB, nullable=True)
    cost_usd = Column(Numeric(12, 6), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    run = relationship("TraceRun", back_populates="spans")
    parent = relationship(
        "TraceSpan",
        remote_side=[id],
        foreign_keys=[parent_span_id],
        primaryjoin="TraceSpan.parent_span_id == TraceSpan.id",
        backref="children",
    )
    evaluations = relationship("Evaluation", back_populates="span", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_spans_run_id", "run_id"),
        Index("idx_spans_parent", "run_id", "parent_span_id"),
        Index("idx_spans_origin", "origin_span_id"),
        Index("idx_spans_group", "rewind_group_id"),
        Index(
            "idx_spans_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class SpanLink(Base):
    """Data-flow and fan-in edges between spans (R3, 13.3).

    Allows modeling multi-parent DAGs where one step consumes outputs of multiple spans.
    """

    __tablename__ = "span_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trace_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_span_id = Column(UUID(as_uuid=True), nullable=False)
    to_span_id = Column(UUID(as_uuid=True), nullable=False)
    link_type = Column(String(20), nullable=False, default="data")

    run = relationship("TraceRun", back_populates="links")

    __table_args__ = (
        Index("idx_span_links_run_id", "run_id"),
        UniqueConstraint("from_span_id", "to_span_id", "link_type", name="uq_span_link"),
    )


class Evaluation(Base):
    """Result of one evaluation phase for a span.

    Each span gets at most 3 evaluations (one per phase).
    The unique constraint on (span_id, phase) enforces this.
    """

    __tablename__ = "evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    span_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trace_spans.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase = Column(String(30), nullable=False)
    verdict = Column(String(20), nullable=False)
    score = Column(Float, nullable=True)
    details = Column(JSONB, default=dict)
    summary = Column(Text, nullable=True)

    # Metadata columns for auditing & debugging (13.3 & 15.5)
    evaluator_version = Column(String(50), nullable=True)
    evaluator_model = Column(String(100), nullable=True)
    prompt_hash = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # Relationships
    span = relationship("TraceSpan", back_populates="evaluations")

    __table_args__ = (
        Index("idx_eval_span_id", "span_id"),
        UniqueConstraint("span_id", "phase", name="uq_eval_span_phase"),
    )

