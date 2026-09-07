from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from axo_endpoint.core.consensus.membership import ClusterMember
from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.storage.backend import StorageBackend
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]

# (rpc_uri, name, version) -> the peer's DATA_STATUS metadata dict, or None on failure/timeout
QueryStatusFn = Callable[[str, str, int], Optional[Dict[str, Any]]]
# (rpc_uri, name, version, chunk_index, chunk_bytes) -> None, fire-and-forget
PushChunkFn = Callable[[str, str, int, int, bytes], None]


@dataclass(frozen=True)
class PeerSyncInfo:
    """Best-effort, advisory snapshot of one peer's last-known replication
    state for one dataset -- not persisted, not itself replicated, purely
    for DATA_INFO to report on."""

    complete: bool
    present_chunks: int
    total_chunks: int
    latency_ms: float
    last_synced_at: float


class BlobReplicator:
    """Leader-only. On each tick, considers every DataRecord this node's
    catalog knows about (including ones it only learned about via replicated
    metadata after a leadership change -- not just ones it personally
    registered), diffs each cluster member's reported chunk presence against
    this node's own, and pushes whatever's missing via the same DATA_CHUNK_PUT
    op a real client uses -- the "same mechanism" for client push and
    leader/follower replication.

    Two gates apply before anything is considered for a given record:
    - leader-completeness: a dataset not yet fully present *here* is skipped
      entirely this tick (never replicate a partial upload).
    - per-kind enable list: a kind not in enabled_kinds (e.g. a
      self-replicating external backend) is never considered at all.

    A third gate applies per (record, peer) pair: once a peer has reported
    complete=True, that pair is skipped entirely (no DATA_STATUS call at all)
    for recheck_seconds -- a DataRecord's chunks never change after
    registration, so there's nothing new to learn by asking again
    immediately. The recheck after that window is what lets the replicator
    notice (and re-push to) a peer that lost its data after being marked
    complete (disk wipe, restarted with a fresh volume, etc.) -- purely
    best-effort self-healing, not a guarantee.
    """

    def __init__(
        self,
        data_registry: DataRegistry,
        storage_backends: Dict[str, StorageBackend],
        chunk_bytes: int,
        rate_limit_bytes_per_second: float,
        enabled_kinds: List[str],
        recheck_seconds: float = 300.0,
        now_fn: Callable[[], float] = time.time,
        logger: _Logger = None,
    ) -> None:
        self._data_registry = data_registry
        self._storage_backends = storage_backends
        self._chunk_bytes = chunk_bytes
        self._rate_limit_bytes_per_second = rate_limit_bytes_per_second
        self._enabled_kinds: Set[str] = set(enabled_kinds)
        self._recheck_seconds = recheck_seconds
        self._now_fn = now_fn
        self._logger: _Logger = logger or DumbLogger()
        self._peer_status: Dict[Tuple[str, int], Dict[str, PeerSyncInfo]] = {}
        self._peer_status_lock = threading.Lock()

    def peer_status_for(self, name: str, version: int) -> Dict[str, PeerSyncInfo]:
        """Read-only snapshot for DataInfoHandler -- a copy, so a concurrent
        tick updating the cache can't mutate what the caller is iterating."""
        with self._peer_status_lock:
            return dict(self._peer_status.get((name, version), {}))

    def _cached_peer_status(self, name: str, version: int, peer_id: str) -> Optional[PeerSyncInfo]:
        with self._peer_status_lock:
            return self._peer_status.get((name, version), {}).get(peer_id)

    def run_tick(
        self,
        is_leader: bool,
        members: List[ClusterMember],
        query_status_fn: QueryStatusFn,
        push_chunk_fn: PushChunkFn,
        elapsed_seconds: float,
    ) -> None:
        """No-op if not leader or there are no peers. Otherwise diffs every
        complete, enabled-kind record against every member not already
        known-complete-and-recently-verified, and pushes whatever chunks
        that member is missing, capped at rate_limit_bytes_per_second *
        elapsed_seconds bytes total this tick (0 or negative rate limit
        means unbounded)."""
        if not is_leader or not members:
            return

        byte_budget = self._rate_limit_bytes_per_second * elapsed_seconds
        bytes_sent = 0.0
        now = self._now_fn()

        for record in self._data_registry.list_records():
            if record.kind not in self._enabled_kinds:
                continue
            leader_status = self._data_registry.status(record.name, record.version)
            if not leader_status.complete:
                continue

            leader_present = set(leader_status.present_chunk_indices)
            for member in members:
                cached = self._cached_peer_status(record.name, record.version, member.peer_id)
                if cached is not None and cached.complete and (now - cached.last_synced_at) < self._recheck_seconds:
                    continue  # already known complete and recently verified -- nothing new to learn

                t0 = time.monotonic()
                peer_metadata = query_status_fn(member.rpc_uri, record.name, record.version)
                latency_ms = (time.monotonic() - t0) * 1000.0
                if peer_metadata is None:
                    continue

                present_chunks = set(peer_metadata.get("present_chunk_indices", []))
                complete = bool(peer_metadata.get("complete", False))
                was_complete = cached.complete if cached is not None else False
                self._record_peer_status(
                    record.name, record.version, member.peer_id,
                    complete=complete, present_chunks=len(present_chunks),
                    total_chunks=record.total_chunks, latency_ms=latency_ms,
                )
                if complete and not was_complete:
                    self._logger.info_event(
                        Event.Data.REPLICATION_COMPLETE,
                        component=Component.BLOB_REPLICATION,
                        data_name=record.name,
                        data_version=record.version,
                        peer_id=member.peer_id,
                    )
                if complete:
                    continue

                for chunk_index in sorted(leader_present - present_chunks):
                    if self._rate_limit_bytes_per_second > 0 and bytes_sent >= byte_budget:
                        break
                    chunk_result = self._data_registry.read_chunk(record.name, record.version, chunk_index)
                    if chunk_result.is_err:
                        continue
                    chunk = chunk_result.unwrap()
                    push_chunk_fn(member.rpc_uri, record.name, record.version, chunk_index, chunk)
                    bytes_sent += len(chunk)

    def _record_peer_status(
        self, name: str, version: int, peer_id: str, *,
        complete: bool, present_chunks: int, total_chunks: int, latency_ms: float,
    ) -> None:
        with self._peer_status_lock:
            per_dataset = self._peer_status.setdefault((name, version), {})
            per_dataset[peer_id] = PeerSyncInfo(
                complete=complete, present_chunks=present_chunks, total_chunks=total_chunks,
                latency_ms=latency_ms, last_synced_at=self._now_fn(),
            )
