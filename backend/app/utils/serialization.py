"""Safe serialization utilities.

Converts arbitrary Python objects to JSON-safe dicts.
Used by the SDK and ingestion layer to handle non-serializable function arguments.
"""

import json
from datetime import datetime, date
from enum import Enum
from uuid import UUID
from typing import Any


def safe_serialize(obj: Any, max_depth: int = 5, _depth: int = 0) -> Any:
    """Convert any Python object to a JSON-safe representation.

    Handles common types (datetime, UUID, Enum, sets, bytes) and falls back
    to str(obj) for anything that can't be serialized. Never raises.

    Args:
        obj: Any Python object.
        max_depth: Maximum nesting depth to prevent infinite recursion.
        _depth: Internal depth tracker.

    Returns:
        A JSON-serializable Python object (dict, list, str, int, float, bool, None).
    """
    if _depth > max_depth:
        return str(obj)

    # Primitives — already JSON safe
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj

    if isinstance(obj, str):
        # Truncate very long strings to prevent payload bloat
        if len(obj) > 10_000:
            return obj[:10_000] + "... [truncated]"
        return obj

    # Common types that need conversion
    if isinstance(obj, UUID):
        return str(obj)

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    if isinstance(obj, Enum):
        return obj.value

    if isinstance(obj, bytes):
        return f"<bytes len={len(obj)}>"

    if isinstance(obj, set):
        return [safe_serialize(item, max_depth, _depth + 1) for item in obj]

    # Dicts
    if isinstance(obj, dict):
        return {
            str(k): safe_serialize(v, max_depth, _depth + 1)
            for k, v in obj.items()
        }

    # Lists and tuples
    if isinstance(obj, (list, tuple)):
        return [safe_serialize(item, max_depth, _depth + 1) for item in obj]

    # Objects with __dict__ (dataclasses, custom objects, etc.)
    if hasattr(obj, "__dict__"):
        try:
            return {
                str(k): safe_serialize(v, max_depth, _depth + 1)
                for k, v in obj.__dict__.items()
                if not k.startswith("_")
            }
        except Exception:
            return str(obj)

    # Last resort — just stringify it
    try:
        return str(obj)
    except Exception:
        return "<unserializable>"


def to_json_string(obj: Any) -> str:
    """Convert any object to a compact JSON string.

    Args:
        obj: Any Python object.

    Returns:
        A JSON string.
    """
    return json.dumps(safe_serialize(obj), separators=(",", ":"), default=str)
