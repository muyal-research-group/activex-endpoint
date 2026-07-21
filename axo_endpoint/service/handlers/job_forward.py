from __future__ import annotations

import time
from typing import Callable, Union

from axo_endpoint.core.errors import MissingFieldError
from axo_endpoint.core.events.bus import EventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.core.runtime import FunctionRuntime
from axo_endpoint.core.storage.backend import StorageBackend
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event
from axo_endpoint.service.handlers.job_submit import submit_job

_Logger = Union[Log, DumbLogger]


class JobForwardHandler(CommandHandler):
    """Runs a job that another endpoint decided (via the leader's
    ConcurrencyLedger) should execute here instead -- shares submit_job()
    with JobSubmitHandler, differing only in that the job_id is supplied by
    the forwarder rather than freshly minted, so the client polling the
    origin endpoint and this endpoint agree on the same id."""

    def __init__(
        self,
        runtime: FunctionRuntime,
        results: StorageBackend,
        event_bus: EventBus,
        function_registry: FunctionRegistry,
        now_fn: Callable[[], float] = time.time,
        logger: _Logger = None,
    ) -> None:
        self._runtime = runtime
        self._results = results
        self._event_bus = event_bus
        self._function_registry = function_registry
        self._now_fn = now_fn
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        job_id = command.envelope.get("job_id")
        if not job_id:
            err = MissingFieldError("job_id is required", context={"fields": ["job_id"]})
            self._logger.info_event(
                Event.Job.SUBMITTED,
                component=Component.HANDLER_JOB_FORWARD,
                status="error",
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        return submit_job(
            command,
            job_id,
            self._runtime,
            self._results,
            self._event_bus,
            self._function_registry,
            self._now_fn,
            self._logger,
        )
