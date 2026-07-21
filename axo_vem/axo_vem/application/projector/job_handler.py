from __future__ import annotations

from typing import Any, Dict

from axo_vem.domain.events import models
from axo_vem.domain.execution.job import Job, JobStatus
from axo_vem.domain.execution.repository import JobRepository

JOB_EVENT_TYPES = frozenset({
    models.JOB_QUEUED, models.JOB_STARTED, models.JOB_COMPLETED, models.JOB_FAILED,
})


def apply(repository: JobRepository, event_type: str, data: Dict[str, Any]) -> None:
    """JobQueued creates the record (the only event guaranteed to arrive
    first); JobStarted/Completed/Failed fetch-then-mutate-then-save, same
    pattern workspace_handler.apply uses for VIRTUAL_ENV_UPDATED, since none
    of the three carry every field JobQueued does (e.g. params)."""
    job_id = data["job_id"]

    if event_type == models.JOB_QUEUED:
        repository.save(Job(
            job_id=job_id,
            function_id=data["function_id"],
            status=JobStatus.QUEUED,
            function_version=data.get("version"),
            params=data.get("params"),
            endpoint_id=data.get("endpoint_id"),
            created_at=data.get("created_at"),
        ))
        return

    job = repository.get(job_id)
    if job is None:
        # Started/Completed/Failed arriving without a prior Queued (e.g.
        # replay starting mid-stream) -- reconstruct a minimal record rather
        # than dropping the event.
        job = Job(
            job_id=job_id, function_id=data["function_id"], status=JobStatus.QUEUED,
            function_version=data.get("version"),
        )

    if event_type == models.JOB_STARTED:
        if data.get("version") is not None:
            job.function_version = data["version"]
        job.start()
    elif event_type == models.JOB_COMPLETED:
        job.complete(duration_ms=data.get("duration_ms"))
    elif event_type == models.JOB_FAILED:
        if data.get("duration_ms") is not None:
            job.duration_ms = data["duration_ms"]
        job.fail()

    repository.save(job)
