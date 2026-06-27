from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, Union

from option import Result

from axo_endpoint.core.errors import InvocationError, MissingFieldError
from axo_endpoint.core.events.bus import Event, EventBus
from axo_endpoint.core.network.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.core.results import FunctionResult
from axo_endpoint.core.runtime import FunctionRuntime, FunctionRuntimeError, InvocationHandle
from axo_endpoint.core.storage.backend import StorageBackend, StorageKey
from axo_endpoint.log import DumbLogger, Log

# Marks a job's result as "not finished yet" while it's still running.
PENDING = "PENDING"

_Logger = Union[Log, DumbLogger]


def build_completion_recorder(
    results: StorageBackend,
    event_bus: EventBus,
    now_fn: Callable[[], float] = time.time,
    logger: _Logger = None,
) -> Callable[[InvocationHandle, "Result[Any, FunctionRuntimeError]"], None]:
    """Creates a function that saves a job's final result and announces that it finished."""

    _logger: _Logger = logger or DumbLogger()

    def on_complete(handle: InvocationHandle, outcome: "Result[Any, FunctionRuntimeError]") -> None:
        """Saves the job's result and emits a JOB_COMPLETED or JOB_FAILED event."""
        now = now_fn()
        if outcome.is_ok:
            result = FunctionResult(job_id=handle.job_id, ok=True, values={"value": outcome.unwrap()})
            event_type = "JOB_COMPLETED"
            _logger.info_event(
                "JOB.COMPLETED",
                component="handler.job_submit",
                status="ok",
                job_id=handle.job_id,
                function_name=handle.function_id,
            )
        else:
            err_msg = str(outcome.unwrap_err())
            result = FunctionResult(job_id=handle.job_id, ok=False, error=err_msg)
            event_type = "JOB_FAILED"
            _logger.info_event(
                "JOB.FAILED",
                component="handler.job_submit",
                status="error",
                job_id=handle.job_id,
                function_name=handle.function_id,
                error_message=err_msg,
            )

        results.put(StorageKey(id=handle.job_id), result)
        event_bus.emit(
            Event(
                event_type=event_type,
                payload={"job_id": handle.job_id, "function_id": handle.function_id},
                timestamp=now,
            )
        )

    return on_complete


class JobSubmitHandler(CommandHandler):
    """Accepts a job to run and returns a job id right away, before it finishes."""

    def __init__(
        self,
        runtime: FunctionRuntime,
        results: StorageBackend,
        event_bus: EventBus,
        job_id_fn: Callable[[], str] = lambda: uuid.uuid4().hex,
        now_fn: Callable[[], float] = time.time,
        logger: _Logger = None,
    ) -> None:
        self._runtime = runtime
        self._results = results
        self._event_bus = event_bus
        self._job_id_fn = job_id_fn
        self._now_fn = now_fn
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        """Starts running the requested function and returns its new job id."""
        t0 = time.monotonic()
        name = command.envelope.get("function_name")
        version = command.envelope.get("function_version")

        if not name or version is None:
            err = MissingFieldError(
                "function_name and function_version are required",
                context={"fields": ["function_name", "function_version"]},
            )
            self._logger.info_event(
                "JOB.SUBMITTED",
                component="handler.job_submit",
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        params: Dict[str, Any] = command.envelope.get("params", {})
        job_id = self._job_id_fn()
        function_ref = StorageKey(id=name, version=version, alias=name)

        self._results.put(StorageKey(id=job_id), FunctionResult(job_id=job_id, ok=False, error=PENDING))
        self._event_bus.emit(
            Event(
                event_type="JOB_SUBMITTED",
                payload={"job_id": job_id, "function_id": function_ref.id},
                timestamp=self._now_fn(),
            )
        )

        invoke_result = self._runtime.invoke(function_ref, job_id, params)
        if invoke_result.is_err:
            raw = invoke_result.unwrap_err()
            err = InvocationError(str(raw), context={"job_id": job_id, "function_name": name, "version": version})
            self._results.put(StorageKey(id=job_id), FunctionResult(job_id=job_id, ok=False, error=err.message))
            self._logger.info_event(
                "JOB.SUBMITTED",
                component="handler.job_submit",
                status="error",
                job_id=job_id,
                function_name=name,
                function_version=version,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err, metadata={"job_id": job_id})

        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            "JOB.SUBMITTED",
            component="handler.job_submit",
            status="ok",
            job_id=job_id,
            function_name=name,
            function_version=version,
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, metadata={"job_id": job_id, "status": "QUEUED"})
