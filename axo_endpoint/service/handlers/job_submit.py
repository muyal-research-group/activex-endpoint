from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional, Union

from option import Result

from axo_endpoint.core.errors import InvocationError, MissingFieldError
from axo_endpoint.core.events.bus import Event as BusEvent, EventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.functions.params_validation import validate_and_fill_params
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.core.results import FunctionResult
from axo_endpoint.core.runtime import FunctionRuntime, FunctionRuntimeError, InvocationHandle
from axo_endpoint.core.storage.backend import StorageBackend, StorageKey
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

# Marks a job's result as "not finished yet" while it's still running.
PENDING = "PENDING"

_Logger = Union[Log, DumbLogger]


def build_completion_recorder(
    results: StorageBackend,
    event_bus: EventBus,
    now_fn: Callable[[], float] = time.time,
    logger: _Logger = None,
    replicate_fn: "Optional[Callable[[FunctionResult], None]]" = None,
) -> Callable[[InvocationHandle, "Result[Any, FunctionRuntimeError]"], None]:
    """Creates a function that saves a job's final result and announces that
    it finished. ``replicate_fn``, if given, is called once after the local
    store/event -- this is the single point every job's completion passes
    through exactly once, regardless of which runtime executed it, so it's
    also the single point cluster-wide result replication hooks in from.
    Left unset (the default), behavior is identical to before this existed."""

    _logger: _Logger = logger or DumbLogger()

    def on_complete(handle: InvocationHandle, outcome: "Result[Any, FunctionRuntimeError]") -> None:
        """Saves the job's result and emits a JOB_COMPLETED or JOB_FAILED event."""
        now = now_fn()
        duration_ms = round((now - handle.started_at) * 1000, 2) if handle.started_at is not None else None
        if outcome.is_ok:
            result = FunctionResult(job_id=handle.job_id, ok=True, values={"value": outcome.unwrap()})
            event_type = "JOB_COMPLETED"
            _logger.info_event(
                Event.Job.COMPLETED,
                component=Component.HANDLER_JOB_SUBMIT,
                status="ok",
                job_id=handle.job_id,
                function_name=handle.function_id,
            )
        else:
            err_msg = str(outcome.unwrap_err())
            result = FunctionResult(job_id=handle.job_id, ok=False, error=err_msg)
            event_type = "JOB_FAILED"
            _logger.info_event(
                Event.Job.FAILED,
                component=Component.HANDLER_JOB_SUBMIT,
                status="error",
                job_id=handle.job_id,
                function_name=handle.function_id,
                error_message=err_msg,
            )

        results.put(StorageKey(id=handle.job_id), result)
        event_bus.emit(
            BusEvent(
                event_type=event_type,
                payload={
                    "job_id": handle.job_id, "function_id": handle.function_id,
                    "function_version": handle.version, "duration_ms": duration_ms,
                },
                timestamp=now,
            )
        )

        if replicate_fn is not None:
            # Never block the pump/worker thread that called on_complete on
            # network I/O -- replication (incl. its own retries/backoff)
            # runs on its own daemon thread, same reasoning as the cold-start
            # dispatch and leader-reconciliation threads elsewhere.
            threading.Thread(target=replicate_fn, args=(result,), daemon=True).start()

    return on_complete


def submit_job(
    command: Command,
    job_id: str,
    runtime: FunctionRuntime,
    results: StorageBackend,
    event_bus: EventBus,
    function_registry: FunctionRegistry,
    now_fn: Callable[[], float] = time.time,
    logger: _Logger = None,
) -> CommandResult:
    """Validates, records, and invokes one job under the given job_id.
    Shared by JobSubmitHandler (job_id freshly minted) and JobForwardHandler
    (job_id supplied by whoever forwarded the job here) so both go through
    identical validation/PENDING-write/invoke logic -- the only difference
    between a normal submission and a forwarded one is where the job_id
    comes from.

    function_id is the catalog lookup key; function_name (if present) is
    kept only for logging -- names aren't unique across users/workspaces
    once function_id is derived from (user_id, virtual_environment_id,
    name), so name alone can no longer resolve a function."""
    _logger: _Logger = logger or DumbLogger()
    t0              = time.monotonic()
    function_id     = command.envelope.get("function_id")
    name            = command.envelope.get("function_name")
    version         = command.envelope.get("function_version")

    if not function_id or version is None:
        err = MissingFieldError(
            "function_id and function_version are required",
            context={"fields": ["function_id", "function_version"]},
        )
        _logger.info_event(
            Event.Job.SUBMITTED,
            component=Component.HANDLER_JOB_SUBMIT,
            status="error",
            duration_ms=round((time.monotonic() - t0) * 1000, 2),
            **err.to_dict(),
        )
        return CommandResult.from_error(err)

    params: Dict[str, Any] = command.envelope.get("params", {})
    function_ref = StorageKey(id=function_id, version=version, alias=function_id)

    lookup_result = function_registry.get(function_ref)
    record = lookup_result.unwrap() if lookup_result.is_ok else None
    if record is not None and record.params_schema:
        validated = validate_and_fill_params(record.params_schema, params)
        if validated.is_err:
            err = validated.unwrap_err()
            _logger.info_event(
                Event.Job.SUBMITTED,
                component=Component.HANDLER_JOB_SUBMIT,
                status="error",
                function_name=name,
                function_version=version,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)
        params = validated.unwrap()

    results.put(StorageKey(id=job_id), FunctionResult(job_id=job_id, ok=False, error=PENDING))
    event_bus.emit(
        BusEvent(
            event_type="JOB_SUBMITTED",
            payload={
                "job_id": job_id, "function_id": function_ref.id,
                "function_version": version, "params": params,
            },
            timestamp=now_fn(),
        )
    )

    invoke_result = runtime.invoke(function_ref, job_id, params)
    if invoke_result.is_err:
        raw = invoke_result.unwrap_err()
        err = InvocationError(str(raw), context={"job_id": job_id, "function_name": name, "version": version})
        results.put(StorageKey(id=job_id), FunctionResult(job_id=job_id, ok=False, error=err.message))
        _logger.error_event(
            Event.Job.SUBMITTED,
            component        = Component.HANDLER_JOB_SUBMIT,
            status           = "error",
            job_id           = job_id,
            function_name    = name,
            function_version = version,
            duration_ms      = round((time.monotonic() - t0) * 1000, 2),
            **err.to_dict(),
        )
        return CommandResult.from_error(err, metadata={"job_id": job_id})

    duration_ms = round((time.monotonic() - t0) * 1000, 2)
    _logger.info_event(
        Event.Job.SUBMITTED,
        component=Component.HANDLER_JOB_SUBMIT,
        status="ok",
        job_id=job_id,
        function_name=name,
        function_version=version,
        duration_ms=duration_ms,
    )
    return CommandResult(ok=True, metadata={"job_id": job_id, "status": "QUEUED"})


class JobSubmitHandler(CommandHandler):
    """Accepts a job to run and returns a job id right away, before it finishes."""

    def __init__(
        self,
        runtime: FunctionRuntime,
        results: StorageBackend,
        event_bus: EventBus,
        function_registry: FunctionRegistry,
        job_id_fn: Callable[[], str] = lambda: uuid.uuid4().hex,
        now_fn: Callable[[], float] = time.time,
        logger: _Logger = None,
    ) -> None:
        self._runtime = runtime
        self._results = results
        self._event_bus = event_bus
        self._function_registry = function_registry
        self._job_id_fn = job_id_fn
        self._now_fn = now_fn
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        """Mints a fresh job id and submits it."""
        return submit_job(
            command,
            self._job_id_fn(),
            self._runtime,
            self._results,
            self._event_bus,
            self._function_registry,
            self._now_fn,
            self._logger,
        )
