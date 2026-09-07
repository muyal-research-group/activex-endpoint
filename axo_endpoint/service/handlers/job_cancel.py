from __future__ import annotations

import time
from typing import Callable, Union

from axo_endpoint.core.errors import JobNotFoundError, MissingFieldError
from axo_endpoint.core.runtime import FunctionRuntime
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class JobCancelHandler(CommandHandler):
    """Stops one job on this endpoint: kills its in-flight worker process or
    dismisses its in-flight container, or drops it if it's still only
    queued. Never leader-proxied -- a job runs on one specific endpoint,
    and only that endpoint's own runtime state can act on it (same category
    as DATA_CHUNK_PUT/DATA_STATUS/CONCURRENCY_RECONCILE_PULL)."""

    def __init__(
        self, runtime: FunctionRuntime, now_fn: Callable[[], float] = time.time, logger: _Logger = None,
    ) -> None:
        self._runtime = runtime
        self._now_fn = now_fn
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        t0 = time.monotonic()
        job_id = command.envelope.get("job_id")
        if not job_id:
            err = MissingFieldError("job_id is required", context={"fields": ["job_id"]})
            self._logger.info_event(
                Event.Job.CANCEL_REQUESTED,
                component=Component.HANDLER_JOB_CANCEL,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        cancelled = self._runtime.cancel(job_id)
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        if not cancelled:
            err = JobNotFoundError(
                "job not found or already finished", context={"job_id": job_id},
            )
            self._logger.info_event(
                Event.Job.CANCEL_REQUESTED,
                component=Component.HANDLER_JOB_CANCEL,
                status="error",
                job_id=job_id,
                duration_ms=duration_ms,
                **err.to_dict(),
            )
            return CommandResult.from_error(err, metadata={"job_id": job_id})

        self._logger.info_event(
            Event.Job.CANCEL_REQUESTED,
            component=Component.HANDLER_JOB_CANCEL,
            status="ok",
            job_id=job_id,
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, metadata={"job_id": job_id, "status": "CANCELLED"})
