from __future__ import annotations

import time
from typing import Union

from axo_endpoint.core.errors import JobNotFoundError, MissingFieldError, StorageFailureError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.core.storage.backend import StorageBackend, StorageKey
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event
from axo_endpoint.service.handlers.job_submit import PENDING

_Logger = Union[Log, DumbLogger]


class JobResultHandler(CommandHandler):
    """Looks up the result of a job by its job id."""

    def __init__(self, results: StorageBackend, logger: _Logger = None) -> None:
        self._results = results
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        """Returns whether a job is still running, finished, or doesn't exist."""
        job_id = command.envelope.get("job_id")
        if not job_id:
            err = MissingFieldError("job_id is required", context={"fields": ["job_id"]})
            self._logger.debug_event(
                Event.Job.RESULT_POLLED,
                component=Component.HANDLER_JOB_RESULT,
                status="error",
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        get_result = self._results.get(StorageKey(id=job_id))
        if get_result.is_err:
            err = StorageFailureError(str(get_result.unwrap_err()), context={"job_id": job_id})
            self._logger.debug_event(
                Event.Job.RESULT_POLLED,
                component=Component.HANDLER_JOB_RESULT,
                job_id=job_id,
                status="error",
                **err.to_dict(),
            )
            return CommandResult.from_error(err, metadata={"job_id": job_id})

        result = get_result.unwrap()
        if result is None:
            err = JobNotFoundError("job not found", context={"job_id": job_id})
            self._logger.debug_event(
                Event.Job.RESULT_POLLED,
                component=Component.HANDLER_JOB_RESULT,
                job_id=job_id,
                status="error",
                **err.to_dict(),
            )
            return CommandResult.from_error(err, metadata={"job_id": job_id})

        if result.error == PENDING:
            self._logger.debug_event(
                Event.Job.RESULT_POLLED,
                component=Component.HANDLER_JOB_RESULT,
                job_id=job_id,
                status="ok",
                job_status="PENDING",
            )
            return CommandResult(ok=True, metadata={"job_id": job_id, "status": "PENDING"})

        job_status = "COMPLETED" if result.ok else "FAILED"
        self._logger.debug_event(
            Event.Job.RESULT_POLLED,
            component=Component.HANDLER_JOB_RESULT,
            job_id=job_id,
            status="ok",
            job_status=job_status,
        )
        return CommandResult(
            ok=True,
            metadata={
                "job_id": job_id,
                "status": job_status,
                "result_ok": result.ok,
                "output": result.output,
                "refs": {k: v.to_str() for k, v in result.refs.items()},
                "error": result.error,
                "duration_ms": result.duration_ms,
                "warnings": result.warnings,
            },
        )
