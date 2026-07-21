from __future__ import annotations

import time
from typing import Union

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.errors import MissingFieldError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class DataChunkPutHandler(CommandHandler):
    """Stores one chunk of already-registered data. Never leader-proxied --
    a follower receiving this from the leader's replication loop IS the
    expected receiver, exactly like the same command sent directly by a real
    client targeting the leader (see DataRegisterHandler's leader_rpc_uri).
    This one handler serves both callers identically -- the "same mechanism"
    for client push and leader/follower replication."""

    def __init__(self, registry: DataRegistry, logger: _Logger = None) -> None:
        self._registry = registry
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        t0 = time.monotonic()
        envelope = command.envelope
        name = envelope.get("name")
        version = envelope.get("version")
        chunk_index = envelope.get("chunk_index")

        if not name or version is None or chunk_index is None:
            err = MissingFieldError(
                "name, version, and chunk_index are required",
                context={"fields": ["name", "version", "chunk_index"]},
            )
            self._logger.info_event(
                Event.Data.CHUNK_STORED,
                component=Component.HANDLER_DATA_CHUNK_PUT,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        result = self._registry.store_chunk(name, version, chunk_index, command.payload)
        if result.is_err:
            err = result.unwrap_err()
            self._logger.info_event(
                Event.Data.CHUNK_STORED,
                component=Component.HANDLER_DATA_CHUNK_PUT,
                status="error",
                data_name=name,
                data_version=version,
                chunk_index=chunk_index,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        status = self._registry.status(name, version)
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            Event.Data.CHUNK_STORED,
            component=Component.HANDLER_DATA_CHUNK_PUT,
            status="ok",
            data_name=name,
            data_version=version,
            chunk_index=chunk_index,
            received_count=len(status.present_chunk_indices),
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, metadata={
            "data_id": name,
            "version": version,
            "received_count": len(status.present_chunk_indices),
            "total_chunks": status.total_chunks,
            "complete": status.complete,
        })
