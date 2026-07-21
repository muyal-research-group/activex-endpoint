from __future__ import annotations

import time
from typing import Union

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.errors import MissingFieldError, StorageFailureError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class DataChunkGetHandler(CommandHandler):
    """Reads one chunk of a registered dataset's bytes back out -- the read
    counterpart of DATA_CHUNK_PUT, letting a client (via axo_vem's
    streaming download route) pull previously-uploaded data back out.

    Never leader-proxied -- same reasoning as DATA_STATUS: this reports (and
    reads from) *this specific node's* own local bytes, not an
    authoritative, leader-mediated view. The caller is responsible for
    targeting a node it already knows is complete (e.g. the leader, per the
    same completeness gate BlobReplicator relies on)."""

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
                Event.Data.CHUNK_READ,
                component=Component.HANDLER_DATA_CHUNK_GET,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        result = self._registry.read_chunk(name, version, chunk_index)
        if result.is_err:
            raw = result.unwrap_err()
            err = StorageFailureError(str(raw), context={"data_name": name, "version": version})
            self._logger.info_event(
                Event.Data.CHUNK_READ,
                component=Component.HANDLER_DATA_CHUNK_GET,
                status="error",
                data_name=name,
                data_version=version,
                chunk_index=chunk_index,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        payload = result.unwrap()
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.debug_event(
            Event.Data.CHUNK_READ,
            component=Component.HANDLER_DATA_CHUNK_GET,
            status="ok",
            data_name=name,
            data_version=version,
            chunk_index=chunk_index,
            chunk_bytes=len(payload),
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, payload=payload, metadata={
            "name": name, "version": version, "chunk_index": chunk_index,
        })
