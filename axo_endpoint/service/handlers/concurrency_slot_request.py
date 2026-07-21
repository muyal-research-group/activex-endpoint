from __future__ import annotations

from typing import Union

from axo_endpoint.core.consensus.concurrency import ConcurrencyLedger
from axo_endpoint.core.consensus.errors import ConcurrencyLedgerNotReadyError
from axo_endpoint.core.errors import MissingFieldError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class ConcurrencySlotRequestHandler(CommandHandler):
    """Leader-side: decides where a job for (function_id, version) should
    run when the requesting endpoint has no idle local container of its
    own. Always wrapped in LeaderProxyHandler -- only ever runs for real on
    whoever is currently leader."""

    def __init__(self, ledger: ConcurrencyLedger, logger: _Logger = None) -> None:
        self._ledger = ledger
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        function_id = command.envelope.get("function_id")
        version = command.envelope.get("version")
        max_concurrency = command.envelope.get("max_concurrency")
        requester_id = command.envelope.get("requester_id")
        if not function_id or version is None or max_concurrency is None or not requester_id:
            err = MissingFieldError(
                "function_id, version, max_concurrency and requester_id are required",
                context={"fields": ["function_id", "version", "max_concurrency", "requester_id"]},
            )
            return CommandResult.from_error(err)

        decision = self._ledger.request_slot(function_id, int(version), int(max_concurrency), requester_id)

        if decision.action == "retry":
            err = ConcurrencyLedgerNotReadyError(
                "concurrency ledger is mid-reconciliation", context={"function_id": function_id, "version": version},
            )
            return CommandResult.from_error(err)

        if decision.action == "granted":
            self._logger.info_event(
                Event.Concurrency.SLOT_GRANTED,
                component=Component.HANDLER_CONCURRENCY_SLOT_REQUEST,
                function_id=function_id,
                version=version,
                slot_index=decision.slot_index,
                requester_id=requester_id,
            )
            return CommandResult(ok=True, metadata={"action": "granted", "slot_index": decision.slot_index})

        self._logger.info_event(
            Event.Concurrency.SLOT_AT_CAPACITY,
            component=Component.HANDLER_CONCURRENCY_SLOT_REQUEST,
            function_id=function_id,
            version=version,
            requester_id=requester_id,
            target_endpoint_id=decision.target_endpoint_id,
        )
        return CommandResult(
            ok=True, metadata={"action": "place", "target_endpoint_id": decision.target_endpoint_id},
        )
