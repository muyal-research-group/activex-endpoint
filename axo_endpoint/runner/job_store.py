from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class JobEntry:
    job_id: str
    status: str           # "PENDING" | "COMPLETED" | "FAILED"
    values: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


class JobStore:
    """Thread-safe in-memory store for job results inside the container runner."""

    def __init__(self) -> None:
        self._store: Dict[str, JobEntry] = {}
        self._lock = threading.Lock()

    def set_pending(self, job_id: str) -> None:
        with self._lock:
            self._store[job_id] = JobEntry(job_id=job_id, status="PENDING")

    def set_result(self, job_id: str, ok: bool, value: Any = None, error: str = "") -> None:
        with self._lock:
            entry = self._store.get(job_id) or JobEntry(job_id=job_id, status="PENDING")
            entry.status = "COMPLETED" if ok else "FAILED"
            entry.values = {"value": value} if ok else {}
            entry.error = error
            self._store[job_id] = entry

    def get(self, job_id: str) -> Optional[JobEntry]:
        with self._lock:
            return self._store.get(job_id)
