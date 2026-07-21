from __future__ import annotations

from typing import Union

from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event as LogEvent
from axo_endpoint.service.container.handle import ContainerStatus
from axo_endpoint.service.container.spawner import ContainerSummoner

_Logger = Union[Log, DumbLogger]


class ConcurrencyReconcilePullHandler(CommandHandler):
    """Returns this endpoint's own live containers, regardless of
    leader/follower status -- modeled on StateSyncPullHandler. A
    newly-elected leader calls this against every peer to rebuild its
    ConcurrencyLedger from ground truth."""

    def __init__(self, summoner: ContainerSummoner, logger: _Logger = None) -> None:
        self._summoner = summoner
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        entries = [
            {"function_id": h.function_id, "version": h.version, "slot_index": h.pool_index}
            for h in self._summoner.list_handles()
            if h.status not in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED)
        ]
        self._logger.debug_event(
            LogEvent.Consensus.SYNC_PULL_SERVED,
            component=Component.HANDLER_CONCURRENCY_RECONCILE_PULL,
            entry_count=len(entries),
        )
        return CommandResult(ok=True, metadata={"entries": entries})
