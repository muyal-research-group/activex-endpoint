from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class Job:
    """Aggregate root tracking one job's execution lifecycle. Shape mirrors
    JobQueued/Started/Completed/Failed (see axo_shared/events/models.py).
    Backed by the dedicated `jobs` Mongo collection via
    infrastructure/database/mongo/job_repository.py's MongoJobRepository,
    fed by application/projector/job_handler.py -- job state is queryable
    directly by job_id (GET /jobs/{job_id}) in addition to still landing in
    the flat unified_activity timeline."""

    job_id: str
    function_id: str
    status: JobStatus
    function_version: Optional[int] = None
    duration_ms: Optional[float] = None
    params: Optional[Dict[str, Any]] = None
    # Sourced from JobQueued's own EventEnvelope endpoint_id/created_at --
    # needed so a job-history row can target the right node for a live
    # JOB_RESULT poll, and so history can be sorted newest-first.
    endpoint_id: Optional[str] = None
    created_at: Optional[str] = None

    def start(self) -> None:
        self.status = JobStatus.STARTED

    def complete(self, duration_ms: Optional[float] = None) -> None:
        self.status = JobStatus.COMPLETED
        self.duration_ms = duration_ms

    def fail(self) -> None:
        self.status = JobStatus.FAILED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "function_id": self.function_id,
            "status": self.status.value,
            "function_version": self.function_version,
            "duration_ms": self.duration_ms,
            "params": self.params,
            "endpoint_id": self.endpoint_id,
            "created_at": self.created_at,
        }
