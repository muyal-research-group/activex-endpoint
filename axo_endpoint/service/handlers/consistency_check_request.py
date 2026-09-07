from __future__ import annotations

from typing import Union

from axo_endpoint.core.consensus.result_consistency import ResultConsistencySweeper
from axo_endpoint.core.errors import MissingFieldError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class ConsistencyCheckRequestHandler(CommandHandler):
    """The one axo_vem -> endpoint request for this feature (alongside
    VIRTUAL_ENV_ASSIGN): either "verify this one job now" (added on top of
    the periodic sweep's normal per-tick budget) or "run a full pass now"
    instead of waiting for the next scheduled tick. Always wrapped in
    LeaderProxyHandler -- only the leader owns the sweeper."""

    def __init__(self, sweeper: ResultConsistencySweeper, logger: _Logger = None) -> None:
        self._sweeper = sweeper
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        job_id = command.envelope.get("job_id")
        manual_full_sync = bool(command.envelope.get("manual_full_sync", False))

        if job_id:
            self._sweeper.request_priority_check(job_id)
            self._logger.info_event(
                Event.ResultConsistency.CHECK_STARTED,
                component=Component.HANDLER_CONSISTENCY_CHECK_REQUEST,
                job_id=job_id,
                mode="priority",
            )
            return CommandResult(ok=True, metadata={"queued": True})

        if manual_full_sync:
            started = self._sweeper.start_manual_sync()
            self._logger.info_event(
                Event.ResultConsistency.CHECK_STARTED,
                component=Component.HANDLER_CONSISTENCY_CHECK_REQUEST,
                mode="manual_full_sync",
                started=started,
            )
            return CommandResult(ok=True, metadata={"started": started})

        err = MissingFieldError(
            "either job_id or manual_full_sync is required", context={"fields": ["job_id", "manual_full_sync"]},
        )
        return CommandResult.from_error(err)
