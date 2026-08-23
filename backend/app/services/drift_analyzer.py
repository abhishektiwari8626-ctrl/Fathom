"""Phase 2 — Semantic Drift Detector.

Evaluates spans where kind = "llm_call" or "processing":
- Extracts text representation from input_data and output_data
- Computes 384-dimension dense embeddings via all-MiniLM-L6-v2 (or fallback vectorizer)
- Computes cosine similarity between input and output embeddings
- Applies score thresholds (>=0.85 pass, 0.70-0.84 warning, <0.70 failure / hallucination)
- Produces embedding vector for trace_spans.embedding column
- Generates structured EvaluationCreate records matching ARCHITECTURE.md Section 5 & 9

Owner: Abhishek
"""

import hashlib
import json
import logging
import math
from typing import Any
from uuid import UUID

from app.config import get_settings
from app.enums import EvaluationPhase, EvaluationVerdict, SpanKind
from app.schemas import EvaluationCreate

logger = logging.getLogger("fathom.evaluator.drift")

_MODEL_INSTANCE = None
_MODEL_LOAD_FAILED = False


def _get_sentence_transformer():
    """Lazily load and cache sentence-transformers model."""
    global _MODEL_INSTANCE, _MODEL_LOAD_FAILED
    if _MODEL_INSTANCE is not None:
        return _MODEL_INSTANCE
    if _MODEL_LOAD_FAILED:
        return None

    try:
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        logger.info("Loading embedding model %s", settings.EMBEDDING_MODEL_NAME)
        _MODEL_INSTANCE = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        return _MODEL_INSTANCE
    except Exception as e:
        logger.warning("Could not load SentenceTransformer (%s). Using fallback vectorizer.", e)
        _MODEL_LOAD_FAILED = True
        return None


def _fallback_embed(text: str, dim: int = 384) -> list[float]:
    """Deterministic, normalized 384-dim term-frequency / n-gram vectorizer fallback.

    Ensures zero external dependency crash if torch / sentence-transformers
    is offline or missing.
    """
    if not text.strip():
        v = [0.0] * dim
        v[0] = 1.0
        return v

    vec = [0.0] * dim
    import re
    words = re.findall(r"\w+", text.lower())

    stopwords = {
        "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with",
        "by", "from", "is", "are", "was", "were", "this", "that", "it", "as", "be",
    }
    content_words = [w for w in words if w not in stopwords] or words

    # Count term frequencies
    counts: dict[str, int] = {}
    for w in content_words:
        counts[w] = counts.get(w, 0) + 1

    # Also add character trigrams for subword robustness
    for w in content_words:
        for i in range(max(0, len(w) - 2)):
            tri = w[i : i + 3]
            counts[tri] = counts.get(tri, 0) + 1

    for term, count in counts.items():
        h = int(hashlib.md5(term.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        # Sublinear TF weighting
        weight = 1.0 + math.log(1.0 + count)
        vec[idx] += weight

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 1e-9:
        vec = [round(x / norm, 6) for x in vec]
    else:
        vec[0] = 1.0

    return vec


def generate_embedding(text: str, dim: int = 384) -> list[float]:
    """Generate a normalized 384-dimension vector embedding for text."""
    model = _get_sentence_transformer()
    if model is not None:
        try:
            emb = model.encode(text, normalize_embeddings=True)
            if hasattr(emb, "tolist"):
                emb = emb.tolist()
            return [round(float(x), 6) for x in emb]
        except Exception as e:
            logger.warning("Model encoding failed: %s. Falling back.", e)

    return _fallback_embed(text, dim=dim)


def _compute_cosine_similarity(vec_a: list[float], vec_b: list[float]) -> tuple[float, float, float]:
    """Calculate cosine similarity and norms of two vectors.

    Returns:
        (cosine_similarity, norm_a, norm_b)
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0, 0.0, 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a <= 1e-9 or norm_b <= 1e-9:
        return 0.0, norm_a, norm_b

    similarity = dot / (norm_a * norm_b)
    # Clamp to [-1.0, 1.0]
    similarity = max(-1.0, min(1.0, similarity))
    return round(similarity, 4), round(norm_a, 4), round(norm_b, 4)


def _extract_text(data: Any) -> str:
    """Extract meaningful plain text representation from arbitrary input/output data."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, (int, float, bool)):
        return str(data)
    if isinstance(data, list):
        return " ".join(_extract_text(item) for item in data if item is not None)
    if isinstance(data, dict):
        # Prioritize key text fields if present
        text_parts = []
        for key in (
            "prompt",
            "content",
            "text",
            "summary",
            "query",
            "system",
            "message",
            "extracted_text",
            "response",
            "results",
            "answer",
            "decision",
        ):
            if key in data and data[key]:
                val = data[key]
                if isinstance(val, (str, int, float, bool)):
                    text_parts.append(str(val))
                elif isinstance(val, (list, dict)):
                    text_parts.append(_extract_text(val))

        if text_parts:
            return " ".join(text_parts).strip()

        # Fallback to serializing all values
        try:
            return " ".join(str(v) for v in data.values() if v is not None).strip()
        except Exception:
            return json.dumps(data)

    return str(data)


def analyze_semantic_drift(
    span_id: UUID,
    kind: str | SpanKind,
    input_data: dict | None = None,
    output_data: dict | None = None,
    threshold: float | None = None,
) -> tuple[EvaluationCreate | None, list[float] | None]:
    """Analyze semantic drift between input and output data of a span.

    Args:
        span_id: UUID of the target span.
        kind: SpanKind of the span (applicable to llm_call, processing, etc.).
        input_data: Input payload dictionary.
        output_data: Output payload dictionary.
        threshold: Drift threshold (default 0.70).

    Returns:
        tuple (EvaluationCreate, embedding_vector):
            - EvaluationCreate with phase=EvaluationPhase.SEMANTIC_DRIFT (or None if not applicable)
            - 384-dim embedding vector to store in trace_spans.embedding
    """
    kind_val = kind.value if isinstance(kind, SpanKind) else str(kind)
    settings = get_settings()
    drift_threshold = threshold if threshold is not None else settings.DRIFT_THRESHOLD

    input_text = _extract_text(input_data)
    output_text = _extract_text(output_data)

    # Compute embeddings
    input_emb = generate_embedding(input_text)
    output_emb = generate_embedding(output_text)

    cosine_sim, norm_a, norm_b = _compute_cosine_similarity(input_emb, output_emb)

    # If using fallback vectorizer, calibrate sparse cosine similarity to dense equivalence
    if _MODEL_INSTANCE is None:
        # Sparse n-gram cosine similarity of 0.40+ corresponds to high topical overlap (0.85+ dense)
        if cosine_sim >= 0.45:
            score = round(min(1.0, 0.85 + (cosine_sim - 0.45) * 0.27), 4)
        elif cosine_sim >= 0.25:
            score = round(0.70 + (cosine_sim - 0.25) * 0.70, 4)
        else:
            score = round(max(0.0, cosine_sim * 2.0), 4)
    else:
        # Direct dense cosine similarity from neural embedding model
        score = max(0.0, round(cosine_sim, 4))

    drift_detected = score < drift_threshold

    # Threshold rules according to ARCHITECTURE.md Section 9:
    # 0.85 - 1.00 -> pass
    # 0.70 - 0.84 -> warning
    # 0.00 - 0.69 -> failure
    if score >= 0.85:
        verdict = EvaluationVerdict.PASS
    elif score >= 0.70:
        verdict = EvaluationVerdict.WARNING
    else:
        verdict = EvaluationVerdict.FAILURE

    details = {
        "input_embedding_norm": norm_a,
        "output_embedding_norm": norm_b,
        "cosine_similarity": cosine_sim,
        "drift_threshold": drift_threshold,
        "drift_detected": drift_detected,
    }

    summary = (
        f"Semantic similarity score is {score:.2f} (threshold: {drift_threshold:.2f}). "
        + ("No drift detected." if not drift_detected else "Potential semantic drift / hallucination detected.")
    )

    evaluation = EvaluationCreate(
        span_id=span_id,
        phase=EvaluationPhase.SEMANTIC_DRIFT,
        verdict=verdict,
        score=score,
        details=details,
        summary=summary,
    )

    # We return the output embedding vector to be updated on trace_spans.embedding
    return evaluation, output_emb
