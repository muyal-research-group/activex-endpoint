from __future__ import annotations

from typing import Union

from axo_endpoint.core.consensus.bucket_sync import BucketRegistrySyncBridge
from axo_endpoint.core.consensus.data_sync import DataRegistrySyncBridge
from axo_endpoint.core.consensus.errors import StaleTermError
from axo_endpoint.core.consensus.registry_sync import RegistrySyncBridge
from axo_endpoint.core.consensus.state_machine import ClusterState, ReplicatedStateMachine, decode_state_changes
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class StateSyncPushHandler(CommandHandler):
    """Receives a leader's replication push and applies it locally.

    Always accepted regardless of our own leader/follower status — a
    follower receiving this IS the expected receiver.
    """

    def __init__(
        self,
        state_machine: ReplicatedStateMachine,
        registry_sync: RegistrySyncBridge,
        data_registry_sync: DataRegistrySyncBridge,
        bucket_registry_sync: BucketRegistrySyncBridge,
        logger: _Logger = None,
    ) -> None:
        self._state_machine = state_machine
        self._registry_sync = registry_sync
        self._data_registry_sync = data_registry_sync
        self._bucket_registry_sync = bucket_registry_sync
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        """Merges the incoming function changes into our local state, rejecting stale terms."""
        term = command.envelope.get("term", 0)
        leader_ids = frozenset(command.envelope.get("leader_ids", []))
        members = frozenset(command.envelope.get("members", []))

        local = self._state_machine.snapshot()
        if term < local.term:
            err = StaleTermError(
                f"push term {term} is older than local term {local.term}",
                context={"incoming_term": term, "local_term": local.term},
            )
            self._logger.info_event(
                Event.Consensus.SYNC_PUSH_REJECTED,
                component=Component.HANDLER_STATE_SYNC_PUSH,
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        function_changes, data_changes, bucket_changes = decode_state_changes(command.payload)
        merged_functions = dict(local.functions)
        merged_functions.update(function_changes)
        merged_data = dict(local.data)
        merged_data.update(data_changes)
        merged_buckets = dict(local.buckets)
        merged_buckets.update(bucket_changes)
        incoming = ClusterState(
            term=term,
            leader_ids=leader_ids,
            members=members,
            functions=merged_functions,
            data=merged_data,
            buckets=merged_buckets,
            version=local.version + 1,
        )
        self._state_machine.apply_remote(incoming)
        self._registry_sync.apply_incoming(function_changes)
        self._data_registry_sync.apply_incoming(data_changes)
        self._bucket_registry_sync.apply_incoming(bucket_changes)

        self._logger.info_event(
            Event.Consensus.SYNC_PUSH_RECEIVED,
            component=Component.HANDLER_STATE_SYNC_PUSH,
            term=term,
            function_count=len(function_changes),
            data_count=len(data_changes),
            bucket_count=len(bucket_changes),
        )
        return CommandResult(ok=True)
