from __future__ import annotations

import time
from typing import Union

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.errors import MissingFieldError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class DataStatusHandler(CommandHandler):
    """Cheap, node-local truth about one (name, version): what this node's
    own storage backend actually has on disk right now. Never leader-proxied
    -- the whole point is to ask a *specific* node (the leader, when a client
    is resuming an upload; a specific follower, when the replication loop is
    diffing what to push) about its own local state, not an authoritative
    cluster-wide view. Deliberately excludes hash fields (see DATA_INFO) so
    it stays cheap enough to call once per peer per dataset every
    replication tick."""

    def __init__(self, registry: DataRegistry, logger: _Logger = None) -> None:
        self._registry = registry
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        t0 = time.monotonic()
        name = command.envelope.get("name")
        version = command.envelope.get("version")

        if not name or version is None:
            err = MissingFieldError("name and version are required", context={"fields": ["name", "version"]})
            self._logger.info_event(
                Event.Data.STATUS_QUERIED,
                component=Component.HANDLER_DATA_STATUS,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        status = self._registry.status(name, version)
        self._logger.debug_event(
            Event.Data.STATUS_QUERIED,
            component=Component.HANDLER_DATA_STATUS,
            status="ok",
            data_name=name,
            data_version=version,
            duration_ms=round((time.monotonic() - t0) * 1000, 2),
        )
        return CommandResult(ok=True, metadata={
            "registered": status.registered,
            "total_chunks": status.total_chunks,
            "chunk_bytes": status.chunk_bytes,
            "total_size": status.total_size,
            "present_chunk_indices": status.present_chunk_indices,
            "complete": status.complete,
        })
