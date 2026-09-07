from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class JobEntry:
    job_id: str
    status: str           # "PENDING" | "COMPLETED" | "FAILED"
    # output mirrors axo_endpoint.core.results.envelope.FunctionResult.output:
    # {"value": ..., "type": "json"} for a JSON-safe return, {"type": "bytes"}
    # when the return had to be cloudpickled instead (see server.py).
    output: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    error: str = ""


class JobStore:
    """Thread-safe in-memory store for job results inside the container runner."""

    def __init__(self) -> None:
        self._store: Dict[str, JobEntry] = {}
        self._lock = threading.Lock()

    def set_pending(self, job_id: str) -> None:
        with self._lock:
            self._store[job_id] = JobEntry(job_id=job_id, status="PENDING")

    def set_result(
        self,
        job_id: str,
        ok: bool,
        output: Optional[Dict[str, Any]] = None,
        warnings: Optional[List[str]] = None,
        error: str = "",
    ) -> None:
        with self._lock:
            entry = self._store.get(job_id) or JobEntry(job_id=job_id, status="PENDING")
            entry.status = "COMPLETED" if ok else "FAILED"
            entry.output = output or {}
            entry.warnings = warnings or []
            entry.error = error
            self._store[job_id] = entry

    def get(self, job_id: str) -> Optional[JobEntry]:
        with self._lock:
            return self._store.get(job_id)
