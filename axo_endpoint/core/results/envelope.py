from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    """The outcome of running one function: success or failure, its data, and pointers to any large data.

    ``output`` is the system-computed envelope around whatever a function
    returned: ``{"value": ..., "type": "json"}`` when the raw return is
    JSON-safe (see is_json_safe_value), or ``{"type": "bytes"}`` when it
    isn't -- in the latter case the actual bytes are registered separately
    and addressed via ``refs["value"]`` instead of inlined here. Function
    authors write no envelope themselves; this shape is built entirely by
    build_completion_recorder."""

    job_id: str
    ok: bool
    output: Dict[str, Any] = field(default_factory=dict)
    refs: Dict[str, StorageKey] = field(default_factory=dict)
    error: str = ""
    duration_ms: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


def encode_function_result(result: FunctionResult) -> bytes:
    """Serializes a FunctionResult to bytes for cluster-wide result
    replication (see core.consensus.result_consistency) -- ``output`` is
    assumed JSON-safe already (build_completion_recorder never puts
    anything else there -- non-JSON-safe payloads go through ``refs``
    instead), same assumption the wire protocol makes elsewhere for job
    results."""
    return json.dumps({
        "job_id": result.job_id,
        "ok": result.ok,
        "output": result.output,
        "refs": {k: v.to_str() for k, v in result.refs.items()},
        "error": result.error,
        "duration_ms": result.duration_ms,
        "warnings": result.warnings,
    }).encode("utf-8")


def decode_function_result(data: bytes) -> FunctionResult:
    """Inverse of encode_function_result()."""
    d = json.loads(data.decode("utf-8"))
    return FunctionResult(
        job_id=d["job_id"],
        ok=d["ok"],
        output=d.get("output", {}),
        refs={k: StorageKey.from_str(v) for k, v in d.get("refs", {}).items()},
        error=d.get("error", ""),
        duration_ms=d.get("duration_ms"),
        warnings=d.get("warnings", []),
    )
