from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set, Tuple

from option import Err, Ok, Result

from axo_endpoint.core.data.chunking import chunk_key, expected_chunk_len, total_chunks_for
from axo_endpoint.core.data.models import (
    DATA_DELETED_EVENT,
    DATA_REGISTERED_EVENT,
    DATA_UPLOAD_COMPLETED_EVENT,
    DataRecord,
    DataStatus,
)
from axo_endpoint.core.dataio.errors import UnknownIORefKindError
from axo_endpoint.core.dataio.protocol import KEY_TYPES
from axo_endpoint.core.errors import (
    ChunkIndexOutOfRangeError,
    ChunkSizeMismatchError,
    DataNotRegisteredError,
    StreamAlreadyFinalizedError,
    StreamNotOpenError,
)
from axo_endpoint.core.events.bus import Event, EventBus
from axo_endpoint.core.storage.backend import StorageBackend, StorageError, StorageKey


@dataclass
class _OpenStream:
    """Ephemeral, process-local bookkeeping for one in-progress function
    output stream. Never touches the catalog and is never replicated -- see
    the plan's "why an open stream must not be a DataRecord" note. Lost if
    the process restarts mid-stream; the chunks already on disk are harmless
    orphans since no catalog entry ever points at them."""

    format: str
    kind: str
    chunk_bytes: int
    next_index: int = 0
    total_size: int = 0
    hasher: Any = field(default_factory=hashlib.sha256)


class DataRegistry:
    """Stores registered data (dataframes/matrices/files) ahead of or during
    a job, addressed the way FunctionRegistry addresses function code.

    Two backends are involved: ``catalog`` holds DataRecord metadata keyed by
    StorageKey (mirrors FunctionRegistry's backend), and ``blob_backends``
    holds the actual chunk bytes -- the same instances resolve_io_request
    reads from, so data registered here is immediately readable via
    dataio.read/iter_chunks(IORef) with zero changes to that call.

    Unlike the original single-blob design, chunk bytes are stored as
    individual permanent objects (see core.data.chunking.chunk_key) and never
    merged into one file -- "complete" is an emergent property (all expected
    chunk keys exist), not a distinct commit step.
    """

    def __init__(
        self,
        catalog: StorageBackend[StorageKey, DataRecord],
        blob_backends: Dict[str, StorageBackend],
        event_bus: EventBus,
    ) -> None:
        self._catalog = catalog
        self._blob_backends = blob_backends
        self._event_bus = event_bus
        self._open_streams: Dict[Tuple[str, int], _OpenStream] = {}
        self._open_streams_lock = threading.Lock()
        # Node-local only -- a locally computed hash is exactly the thing
        # hash_verified is meant to catch divergence in, so it must never be
        # replicated or shared across nodes.
        self._hash_cache: Dict[Tuple[str, int], Tuple[str, bool]] = {}
        # Node-local, never replicated -- guards DATA_UPLOAD_COMPLETED_EVENT
        # against firing more than once per (name, version) on this node
        # (e.g. a duplicate/retried last-chunk PUT).
        self._completed_uploads: Set[Tuple[str, int]] = set()
        self._completed_uploads_lock = threading.Lock()

    # ---- registration (metadata known upfront, e.g. a client upload) ----

    def register(
        self,
        name: str,
        version: int,
        format: str,
        kind: str,
        total_size: int,
        chunk_bytes: int,
        now: float,
        content_hash: Optional[str] = None,
        content_hash_algo: str = "sha256",
    ) -> Result[DataRecord, StorageError]:
        if kind not in self._blob_backends or kind not in KEY_TYPES:
            return Err(UnknownIORefKindError(f"no storage backend for kind={kind!r}", context={"kind": kind}))

        record = DataRecord(
            name=name, version=version, alias=name, format=format, kind=kind,
            total_size=total_size, chunk_bytes=chunk_bytes,
            total_chunks=total_chunks_for(total_size, chunk_bytes),
            created_at=now, declared_hash=content_hash, content_hash_algo=content_hash_algo,
        )
        put_result = self._catalog.put(StorageKey(id=name, version=version, alias=name), record)
        if put_result.is_err:
            return Err(put_result.unwrap_err())

        self._emit_registered(record, now)
        # A zero-chunk record (total_size == 0) has no chunks for
        # store_chunk() to ever complete it via -- it's complete the instant
        # it's registered, same as status()'s own total_chunks == 0 case.
        if record.total_chunks == 0 and self._mark_completed_if_first_time(name, version):
            self._emit_upload_completed(record, now)
        return Ok(record)

    def get(self, key: StorageKey) -> Result[Optional[DataRecord], StorageError]:
        return self._catalog.get(key)

    def list_records(self) -> list:
        """Every DataRecord this node's catalog currently knows about --
        used by the replication loop, which must consider every registered
        dataset (including ones this node only learned about via replicated
        metadata after a leadership change), not just ones it personally
        registered. Relies on the catalog backend being an
        InMemoryStorageBackend (true for every current/planned construction
        site); StorageBackend itself doesn't declare enumeration since
        nothing else needs it."""
        return self._catalog.values()

    def _get_record(self, name: str, version: int) -> Optional[DataRecord]:
        result = self._catalog.get(StorageKey(id=name, version=version, alias=name))
        if result.is_err:
            return None
        return result.unwrap()

    def _emit_registered(self, record: DataRecord, now: float) -> None:
        """format/kind/total_size are carried alongside data_id/version/
        total_chunks so ExternalEventForwardingBridge.on_data_registered can
        forward a complete DataRegistered event without a registry lookup
        it doesn't hold a reference for -- nothing else consuming this
        event needs the payload kept thin."""
        self._event_bus.emit(Event(
            event_type=DATA_REGISTERED_EVENT,
            payload={
                "data_id": record.name, "version": record.version, "total_chunks": record.total_chunks,
                "format": record.format, "kind": record.kind, "total_size": record.total_size,
            },
            timestamp=now,
        ))

    def _emit_upload_completed(self, record: DataRecord, now: float) -> None:
        self._event_bus.emit(Event(
            event_type=DATA_UPLOAD_COMPLETED_EVENT,
            payload={"data_id": record.name, "version": record.version},
            timestamp=now,
        ))

    def _mark_completed_if_first_time(self, name: str, version: int) -> bool:
        """Returns True the first time this (name, version) is observed
        complete on this node, False on every subsequent call -- the guard
        that keeps _emit_upload_completed a one-shot signal."""
        key = (name, version)
        with self._completed_uploads_lock:
            if key in self._completed_uploads:
                return False
            self._completed_uploads.add(key)
            return True

    def _is_fully_present(self, record: DataRecord) -> bool:
        backend = self._blob_backends[record.kind]
        for i in range(record.total_chunks):
            exists_result = backend.exists(chunk_key(record.kind, record.name, record.version, i))
            if exists_result.is_err or not exists_result.unwrap():
                return False
        return True

    # ---- deletion ----

    def delete(self, name: str, version: int, now: float) -> Result[None, StorageError]:
        """Removes this node's own catalog entry and chunk bytes for
        (name, version) -- best-effort on the chunks (a missing chunk isn't
        an error, per StorageBackend.delete()'s own contract; a genuine
        backend failure on one chunk doesn't block removing the rest or the
        catalog entry, since a half-deleted record is no more useful kept
        around than a fully-deleted one). Emits DATA_DELETED_EVENT once,
        which is what drives both consensus replication (removing this key
        from every follower too) and the external forward that flips the
        axo_vem read model."""
        record = self._get_record(name, version)
        if record is None:
            return Err(DataNotRegisteredError(
                f"{name}:{version} is not registered", context={"name": name, "version": version},
            ))
        backend = self._blob_backends.get(record.kind)
        if backend is not None:
            for i in range(record.total_chunks):
                backend.delete(chunk_key(record.kind, name, version, i))

        delete_result = self._catalog.delete(StorageKey(id=name, version=version, alias=name))
        if delete_result.is_err:
            return Err(delete_result.unwrap_err())

        with self._completed_uploads_lock:
            self._completed_uploads.discard((name, version))
        self._hash_cache.pop((name, version), None)

        self._event_bus.emit(Event(
            event_type=DATA_DELETED_EVENT,
            payload={"data_id": name, "version": version},
            timestamp=now,
        ))
        return Ok(None)

    # ---- chunk storage (metadata already registered) ----

    def store_chunk(
        self, name: str, version: int, chunk_index: int, data: bytes, now: Optional[float] = None,
    ) -> Result[DataRecord, StorageError]:
        record = self._get_record(name, version)
        if record is None:
            return Err(DataNotRegisteredError(
                f"{name}:{version} is not registered", context={"name": name, "version": version},
            ))
        if chunk_index < 0 or chunk_index >= record.total_chunks:
            return Err(ChunkIndexOutOfRangeError(
                f"chunk_index {chunk_index} out of range [0, {record.total_chunks})",
                context={
                    "name": name, "version": version,
                    "chunk_index": chunk_index, "total_chunks": record.total_chunks,
                },
            ))
        expected_len = expected_chunk_len(record.total_size, record.chunk_bytes, chunk_index)
        if len(data) != expected_len:
            return Err(ChunkSizeMismatchError(
                f"chunk {chunk_index} expected {expected_len} bytes, got {len(data)}",
                context={
                    "name": name, "version": version, "chunk_index": chunk_index,
                    "expected": expected_len, "actual": len(data),
                },
            ))
        backend = self._blob_backends[record.kind]
        put_result = backend.put(chunk_key(record.kind, name, version, chunk_index), data)
        if put_result.is_err:
            return Err(put_result.unwrap_err())

        if self._is_fully_present(record) and self._mark_completed_if_first_time(name, version):
            self._emit_upload_completed(record, now if now is not None else time.time())

        return Ok(record)

    def read_chunk(self, name: str, version: int, chunk_index: int) -> Result[bytes, StorageError]:
        record = self._get_record(name, version)
        if record is None:
            return Err(DataNotRegisteredError(
                f"{name}:{version} is not registered", context={"name": name, "version": version},
            ))
        backend = self._blob_backends[record.kind]
        get_result = backend.get(chunk_key(record.kind, name, version, chunk_index))
        if get_result.is_err:
            return Err(get_result.unwrap_err())
        value = get_result.unwrap()
        if value is None:
            return Err(DataNotRegisteredError(
                f"chunk {chunk_index} of {name}:{version} missing locally",
                context={"name": name, "version": version, "chunk_index": chunk_index},
            ))
        return Ok(value)

    def read_whole(self, name: str, version: int) -> Result[bytes, StorageError]:
        record = self._get_record(name, version)
        if record is None:
            return Err(DataNotRegisteredError(
                f"{name}:{version} is not registered", context={"name": name, "version": version},
            ))
        parts = []
        for i in range(record.total_chunks):
            chunk_result = self.read_chunk(name, version, i)
            if chunk_result.is_err:
                return Err(chunk_result.unwrap_err())
            parts.append(chunk_result.unwrap())
        return Ok(b"".join(parts))

    def register_and_store(
        self,
        name: str,
        version: int,
        format: str,
        kind: str,
        data: bytes,
        now: float,
        chunk_bytes: int = 262144,
        content_hash: Optional[str] = None,
        content_hash_algo: str = "sha256",
    ) -> Result[DataRecord, StorageError]:
        """Convenience for a caller that already holds the whole blob in
        memory (internal callers, examples, tests) -- drives the exact same
        register()+store_chunk() path an external client would, not a
        parallel implementation."""
        register_result = self.register(
            name, version, format, kind, len(data), chunk_bytes, now,
            content_hash=content_hash, content_hash_algo=content_hash_algo,
        )
        if register_result.is_err:
            return register_result
        record = register_result.unwrap()
        for i in range(record.total_chunks):
            start = i * chunk_bytes
            chunk_result = self.store_chunk(name, version, i, data[start:start + chunk_bytes])
            if chunk_result.is_err:
                return Err(chunk_result.unwrap_err())
        return Ok(record)

    # ---- status ----

    def status(self, name: str, version: int) -> DataStatus:
        record = self._get_record(name, version)
        if record is None:
            return DataStatus(
                registered=False, name=name, version=version, format="", kind="",
                total_size=0, chunk_bytes=0, total_chunks=0, present_chunk_indices=[],
                complete=False, progress_ratio=0.0, declared_hash=None,
                computed_hash=None, hash_verified=None,
            )

        backend = self._blob_backends.get(record.kind)
        present = []
        if backend is not None:
            for i in range(record.total_chunks):
                exists_result = backend.exists(chunk_key(record.kind, name, version, i))
                if exists_result.is_ok and exists_result.unwrap():
                    present.append(i)
        complete = len(present) == record.total_chunks
        progress_ratio = 1.0 if record.total_chunks == 0 else len(present) / record.total_chunks

        computed_hash: Optional[str] = None
        hash_verified: Optional[bool] = None
        if complete:
            cache_key = (name, version)
            cached = self._hash_cache.get(cache_key)
            if cached is None:
                computed_hash = self._compute_hash(record)
                hash_verified = record.declared_hash is not None and computed_hash == record.declared_hash
                self._hash_cache[cache_key] = (computed_hash, hash_verified)
            else:
                computed_hash, hash_verified = cached

        return DataStatus(
            registered=True, name=name, version=version, format=record.format, kind=record.kind,
            total_size=record.total_size, chunk_bytes=record.chunk_bytes, total_chunks=record.total_chunks,
            present_chunk_indices=present, complete=complete, progress_ratio=progress_ratio,
            declared_hash=record.declared_hash, computed_hash=computed_hash, hash_verified=hash_verified,
        )

    def _compute_hash(self, record: DataRecord) -> str:
        """Streams every chunk through an incremental hasher -- bounded
        memory, computed once (status() caches the result once complete)."""
        hasher = hashlib.new(record.content_hash_algo)
        backend = self._blob_backends[record.kind]
        for i in range(record.total_chunks):
            get_result = backend.get(chunk_key(record.kind, record.name, record.version, i))
            value = get_result.unwrap() if get_result.is_ok else None
            hasher.update(value or b"")
        return hasher.hexdigest()

    # ---- streaming writes (size unknown upfront, e.g. function output) ----

    def open_stream(self, name: str, version: int, format: str, kind: str, chunk_bytes: int) -> None:
        """Starts an ephemeral, process-local, unreplicated stream -- no
        catalog entry, no DATA_REGISTERED_EVENT, so it's invisible to
        replication/status/info until finalize_stream()."""
        with self._open_streams_lock:
            self._open_streams[(name, version)] = _OpenStream(format=format, kind=kind, chunk_bytes=chunk_bytes)

    def append_chunk(self, name: str, version: int, data: bytes) -> Result[int, StorageError]:
        with self._open_streams_lock:
            stream = self._open_streams.get((name, version))
            if stream is None:
                return Err(StreamNotOpenError(
                    f"no open stream for {name}:{version}", context={"name": name, "version": version},
                ))
            backend = self._blob_backends.get(stream.kind)
            if backend is None:
                return Err(UnknownIORefKindError(
                    f"no storage backend for kind={stream.kind!r}", context={"kind": stream.kind},
                ))
            index = stream.next_index
            put_result = backend.put(chunk_key(stream.kind, name, version, index), data)
            if put_result.is_err:
                return Err(put_result.unwrap_err())
            stream.hasher.update(data)
            stream.total_size += len(data)
            stream.next_index += 1
            return Ok(index)

    def finalize_stream(self, name: str, version: int, now: float) -> Result[DataRecord, StorageError]:
        with self._open_streams_lock:
            stream = self._open_streams.pop((name, version), None)
        if stream is None:
            return Err(StreamAlreadyFinalizedError(
                f"no open stream for {name}:{version} (already finalized or never opened)",
                context={"name": name, "version": version},
            ))

        record = DataRecord(
            name=name, version=version, alias=name, format=stream.format, kind=stream.kind,
            total_size=stream.total_size, chunk_bytes=stream.chunk_bytes, total_chunks=stream.next_index,
            created_at=now, declared_hash=stream.hasher.hexdigest(), content_hash_algo="sha256",
        )
        put_result = self._catalog.put(StorageKey(id=name, version=version, alias=name), record)
        if put_result.is_err:
            return Err(put_result.unwrap_err())

        self._emit_registered(record, now)
        # Every chunk was already written via append_chunk() before this call
        # -- unlike register()+store_chunk(), there's no separate pending
        # window here, so fire the completion signal in the same breath.
        if self._mark_completed_if_first_time(name, version):
            self._emit_upload_completed(record, now)
        return Ok(record)
