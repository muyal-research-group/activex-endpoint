from __future__ import annotations

from typing import Union

from axo_endpoint.core.consensus.concurrency import ConcurrencyLedger
from axo_endpoint.core.errors import MissingFieldError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class ConcurrencySlotReleaseHandler(CommandHandler):
    """Leader-side: frees a previously-granted slot. Fire-and-forget from the
    caller's point of view -- always wrapped in LeaderProxyHandler so it
    still reaches whoever is actually leader, but the result is ignored."""

    def __init__(self, ledger: ConcurrencyLedger, logger: _Logger = None) -> None:
        self._ledger = ledger
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        function_id = command.envelope.get("function_id")
        version = command.envelope.get("version")
        slot_index = command.envelope.get("slot_index")
        endpoint_id = command.envelope.get("endpoint_id")
        if not function_id or version is None or slot_index is None or not endpoint_id:
            err = MissingFieldError(
                "function_id, version, slot_index and endpoint_id are required",
                context={"fields": ["function_id", "version", "slot_index", "endpoint_id"]},
            )
            return CommandResult.from_error(err)

        self._ledger.release_slot(function_id, int(version), int(slot_index), endpoint_id)
        self._logger.info_event(
            Event.Concurrency.SLOT_RELEASED,
            component=Component.HANDLER_CONCURRENCY_SLOT_RELEASE,
            function_id=function_id,
            version=version,
            slot_index=slot_index,
            endpoint_id=endpoint_id,
        )
        return CommandResult(ok=True)
