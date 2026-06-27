from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from axo_endpoint.core.storage.backend import StorageKey

_JSON_SAFE_SCALARS = (str, int, float, bool, type(None))


def is_json_safe_value(value: Any) -> bool:
    """Checks whether a value is simple enough to store directly, rather than needing a separate storage reference."""
    if isinstance(value, _JSON_SAFE_SCALARS):
        return True
    if isinstance(value, list):
        return all(is_json_safe_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_safe_value(val) for key, val in value.items())
    return False


@dataclass(frozen=True)
class FunctionResult:
    """The outcome of running one function: success or failure, its data, and pointers to any large data."""

    job_id: str
    ok: bool
    values: Dict[str, Any] = field(default_factory=dict)
    refs: Dict[str, StorageKey] = field(default_factory=dict)
    error: str = ""
