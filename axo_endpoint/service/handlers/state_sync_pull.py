from __future__ import annotations

from typing import Union

from axo_endpoint.core.consensus.state_machine import ReplicatedStateMachine, encode_cluster_state
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class StateSyncPullHandler(CommandHandler):
    """Returns this node's current ClusterState snapshot, regardless of leader/follower status."""

    def __init__(self, state_machine: ReplicatedStateMachine, logger: _Logger = None) -> None:
        self._state_machine = state_machine
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        """Serializes and returns the current snapshot."""
        state = self._state_machine.snapshot()
        self._logger.info_event(
            Event.Consensus.SYNC_PULL_SERVED,
            component=Component.HANDLER_STATE_SYNC_PULL,
            function_count=len(state.functions),
        )
        return CommandResult(ok=True, payload=encode_cluster_state(state))
