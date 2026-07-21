from __future__ import annotations

import dataclasses
import time
from typing import Union

from axo_shared.activity.models import ActivityRecord
from axo_shared.activity.repository import Repository
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class ActivityListHandler(CommandHandler):
    """Reads back recorded activity -- purely local per-node, like METRICS;
    not leader-gated (every node tracks its own local activity)."""

    def __init__(self, repository: Repository[ActivityRecord], logger: _Logger = None) -> None:
        self._repository = repository
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        t0 = time.monotonic()
        function_id = command.envelope.get("function_id")
        limit = command.envelope.get("limit", 100)

        if function_id:
            records = self._repository.list_by_function_id(function_id, limit=limit)
        else:
            records = self._repository.list_recent(limit=limit)

        self._logger.debug_event(
            Event.Activity.LISTED,
            component=Component.HANDLER_ACTIVITY_LIST,
            status="ok",
            function_id=function_id,
            count=len(records),
            duration_ms=round((time.monotonic() - t0) * 1000, 2),
        )
        return CommandResult(ok=True, metadata={"records": [dataclasses.asdict(r) for r in records]})
