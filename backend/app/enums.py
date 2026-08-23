"""Shared enums used across all Fathom components.

Every team member MUST use these exact values.
Do NOT create synonyms or variations.
"""

from enum import Enum


class SpanStatus(str, Enum):
    """Status of an individual trace span."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REWOUND = "rewound"


class SpanKind(str, Enum):
    """Type of operation a span represents."""

    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    RETRIEVAL = "retrieval"
    PROCESSING = "processing"
    AGENT_DECISION = "agent_decision"


class EvaluationPhase(str, Enum):
    """Which phase of the 3-phase evaluator produced this evaluation."""

    TOOL_CHECK = "tool_check"
    SEMANTIC_DRIFT = "semantic_drift"
    JUDGE_LLM = "judge_llm"


class EvaluationVerdict(str, Enum):
    """Result of an evaluation phase."""

    PASS = "pass"
    WARNING = "warning"
    FAILURE = "failure"


class RunStatus(str, Enum):
    """Status of an entire trace run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REWOUND = "rewound"
