from __future__ import annotations

import time
from typing import Union

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.errors import MissingFieldError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event
from axo_endpoint.service.blob_replication import BlobReplicator

_Logger = Union[Log, DumbLogger]


class DataInfoHandler(CommandHandler):
    """Heavier, leader-aggregated status query: size, chunk size, progress,
    content hash (declared + locally verified), and per-peer replication
    state. Leader-gated (via LeaderProxyHandler, like DATA_REGISTER) so the
    answer is authoritative -- deliberately separate from DATA_STATUS, which
    must stay a cheap single-node probe called every replication tick."""

    def __init__(self, registry: DataRegistry, replicator: BlobReplicator, logger: _Logger = None) -> None:
        self._registry = registry
        self._replicator = replicator
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        t0 = time.monotonic()
        name = command.envelope.get("name")
        version = command.envelope.get("version")

        if not name or version is None:
            err = MissingFieldError("name and version are required", context={"fields": ["name", "version"]})
            self._logger.info_event(
                Event.Data.INFO_QUERIED,
                component=Component.HANDLER_DATA_INFO,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        status = self._registry.status(name, version)
        peer_status = self._replicator.peer_status_for(name, version)
        replicas = [
            {
                "peer_id": peer_id,
                "complete": info.complete,
                "present_chunks": info.present_chunks,
                "total_chunks": info.total_chunks,
                "latency_ms": info.latency_ms,
                "last_synced_at": info.last_synced_at,
            }
            for peer_id, info in peer_status.items()
        ]
        replica_count = sum(1 for info in peer_status.values() if info.complete)

        self._logger.debug_event(
            Event.Data.INFO_QUERIED,
            component=Component.HANDLER_DATA_INFO,
            status="ok",
            data_name=name,
            data_version=version,
            duration_ms=round((time.monotonic() - t0) * 1000, 2),
        )
        return CommandResult(ok=True, metadata={
            "name": name,
            "version": version,
            "format": status.format,
            "kind": status.kind,
            "total_size": status.total_size,
            "chunk_bytes": status.chunk_bytes,
            "total_chunks": status.total_chunks,
            "progress_ratio": status.progress_ratio,
            "declared_hash": status.declared_hash,
            "computed_hash": status.computed_hash,
            "hash_verified": status.hash_verified,
            "replica_count": replica_count,
            "replicas": replicas,
        })
