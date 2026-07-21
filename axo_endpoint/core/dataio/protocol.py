from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Callable, Dict, Optional, Tuple, Type

from option import Err, Ok, Result

from axo_endpoint.core.dataio.errors import (
    DataIOError,
    IOBackendError,
    IONotFoundError,
    UnknownIOOpError,
    UnknownIORefKindError,
)
from axo_endpoint.core.dataio.ref import IORef
from axo_endpoint.core.errors import AxoError
from axo_endpoint.core.storage.backend import Key, StorageBackend, StorageKey
from axo_endpoint.core.storage.filesystem import FsKey

if TYPE_CHECKING:
    from axo_endpoint.core.data import DataRegistry

READ = "read"
WRITE = "write"
CHUNK_STATUS = "chunk_status"
READ_CHUNK = "read_chunk"
OPEN_STREAM = "open_stream"
APPEND_CHUNK = "append_chunk"
FINALIZE_STREAM = "finalize_stream"

# Maps an IORef.kind to the concrete Key subclass that parses/encodes its
# .location string -- a fixed, compile-time-known mapping of *kinds this
# build understands*, the same plain-module-dict precedent as
# core.dataio.formats.FORMATS is for codecs.
KEY_TYPES: Dict[str, Type[Key]] = {"fs": FsKey}

_DEFAULT_CHUNK_BYTES = 262144


def resolve_io_request(
    op: str,
    ref: IORef,
    data: Optional[bytes],
    storage_backends: Dict[str, StorageBackend],
    data_registry: Optional["DataRegistry"] = None,
    now_fn: Callable[[], float] = time.time,
) -> Result[bytes, DataIOError]:
    """Services one io_request identically regardless of which transport carried
    it in -- the only place either pump loop needs to know about storage backends
    or the DataRegistry. ``data_registry`` is optional -- a caller with no
    DataRegistry configured just never resolves registered-data refs, falling
    back to plain ad-hoc backend reads/writes for every op that supports it."""
    if op == READ:
        return _read(ref, storage_backends, data_registry)
    if op == WRITE:
        return _write(ref, data, storage_backends)
    if op == CHUNK_STATUS:
        return _chunk_status(ref, data_registry)
    if op == READ_CHUNK:
        return _read_chunk(ref, data_registry)
    if op == OPEN_STREAM:
        return _open_stream(ref, data, data_registry)
    if op == APPEND_CHUNK:
        return _append_chunk(ref, data, data_registry)
    if op == FINALIZE_STREAM:
        return _finalize_stream(ref, data_registry, now_fn)
    return Err(UnknownIOOpError(f"unknown io op {op!r}", context={"op": op}))


def _parse_registered_ref(location: str) -> Optional[Tuple[str, int]]:
    """Splits "name/version" -- the convention a DataRegistry-backed ref's
    location follows (see DataRegistry/core.data.chunking). Returns None if
    it doesn't parse that way, which just means it's an ordinary ad-hoc
    dataio.write() location -- those are never DataRegistry refs."""
    name, _, version_str = location.rpartition("/")
    if not name or not version_str.isdigit():
        return None
    return name, int(version_str)


def _backend_and_key(ref: IORef, storage_backends: Dict[str, StorageBackend]):
    backend = storage_backends.get(ref.kind)
    key_type = KEY_TYPES.get(ref.kind)
    if backend is None or key_type is None:
        return None, None
    return backend, key_type.from_str(ref.location)


def _read(
    ref: IORef,
    storage_backends: Dict[str, StorageBackend],
    data_registry: Optional["DataRegistry"],
) -> Result[bytes, DataIOError]:
    if data_registry is not None:
        parsed = _parse_registered_ref(ref.location)
        if parsed is not None:
            name, version = parsed
            record_result = data_registry.get(StorageKey(id=name, version=version, alias=name))
            if record_result.is_ok and record_result.unwrap() is not None:
                read_result = data_registry.read_whole(name, version)
                if read_result.is_err:
                    return Err(_wrap_error(read_result.unwrap_err(), ref))
                return Ok(read_result.unwrap())

    backend, key = _backend_and_key(ref, storage_backends)
    if backend is None:
        return Err(UnknownIORefKindError(f"no storage backend for kind={ref.kind!r}", context={"kind": ref.kind}))
    get_result = backend.get(key)
    if get_result.is_err:
        return Err(_wrap_error(get_result.unwrap_err(), ref))
    value = get_result.unwrap()
    if value is None:
        return Err(IONotFoundError(f"no blob at {ref.location!r}", context={"location": ref.location, "kind": ref.kind}))
    return Ok(value)


def _write(
    ref: IORef, data: Optional[bytes], storage_backends: Dict[str, StorageBackend],
) -> Result[bytes, DataIOError]:
    backend, key = _backend_and_key(ref, storage_backends)
    if backend is None:
        return Err(UnknownIORefKindError(f"no storage backend for kind={ref.kind!r}", context={"kind": ref.kind}))
    put_result = backend.put(key, data or b"")
    if put_result.is_err:
        return Err(_wrap_error(put_result.unwrap_err(), ref))
    return Ok(b"")


def _require_registry(
    ref: IORef, data_registry: Optional["DataRegistry"],
) -> Optional[DataIOError]:
    if data_registry is None:
        return UnknownIORefKindError("no data registry configured for this endpoint", context={"kind": ref.kind})
    return None


def _require_parsed_ref(ref: IORef) -> Result[Tuple[str, int], DataIOError]:
    parsed = _parse_registered_ref(ref.location)
    if parsed is None:
        return Err(UnknownIORefKindError(
            f"{ref.location!r} is not a registered-data ref (expected \"name/version\")",
            context={"location": ref.location},
        ))
    return Ok(parsed)


def _chunk_status(ref: IORef, data_registry: Optional["DataRegistry"]) -> Result[bytes, DataIOError]:
    missing = _require_registry(ref, data_registry)
    if missing is not None:
        return Err(missing)
    parsed_result = _require_parsed_ref(ref)
    if parsed_result.is_err:
        return Err(parsed_result.unwrap_err())
    name, version = parsed_result.unwrap()

    status = data_registry.status(name, version)
    if not status.registered:
        return Err(IONotFoundError(f"{name}:{version} is not registered", context={"name": name, "version": version}))
    payload = json.dumps({"total_chunks": status.total_chunks, "chunk_bytes": status.chunk_bytes}).encode("utf-8")
    return Ok(payload)


def _read_chunk(ref: IORef, data_registry: Optional["DataRegistry"]) -> Result[bytes, DataIOError]:
    missing = _require_registry(ref, data_registry)
    if missing is not None:
        return Err(missing)
    if ref.chunk_index is None:
        return Err(UnknownIOOpError("read_chunk requires ref.chunk_index", context={"location": ref.location}))
    parsed_result = _require_parsed_ref(ref)
    if parsed_result.is_err:
        return Err(parsed_result.unwrap_err())
    name, version = parsed_result.unwrap()

    read_result = data_registry.read_chunk(name, version, ref.chunk_index)
    if read_result.is_err:
        return Err(_wrap_error(read_result.unwrap_err(), ref))
    return Ok(read_result.unwrap())


def _open_stream(
    ref: IORef, data: Optional[bytes], data_registry: Optional["DataRegistry"],
) -> Result[bytes, DataIOError]:
    missing = _require_registry(ref, data_registry)
    if missing is not None:
        return Err(missing)
    parsed_result = _require_parsed_ref(ref)
    if parsed_result.is_err:
        return Err(parsed_result.unwrap_err())
    name, version = parsed_result.unwrap()

    chunk_bytes = _DEFAULT_CHUNK_BYTES
    if data:
        try:
            chunk_bytes = int(json.loads(data.decode("utf-8")).get("chunk_bytes", chunk_bytes))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            pass
    data_registry.open_stream(name, version, format=ref.format, kind=ref.kind, chunk_bytes=chunk_bytes)
    return Ok(b"")


def _append_chunk(
    ref: IORef, data: Optional[bytes], data_registry: Optional["DataRegistry"],
) -> Result[bytes, DataIOError]:
    missing = _require_registry(ref, data_registry)
    if missing is not None:
        return Err(missing)
    parsed_result = _require_parsed_ref(ref)
    if parsed_result.is_err:
        return Err(parsed_result.unwrap_err())
    name, version = parsed_result.unwrap()

    append_result = data_registry.append_chunk(name, version, data or b"")
    if append_result.is_err:
        return Err(_wrap_error(append_result.unwrap_err(), ref))
    return Ok(str(append_result.unwrap()).encode("utf-8"))


def _finalize_stream(
    ref: IORef, data_registry: Optional["DataRegistry"], now_fn: Callable[[], float],
) -> Result[bytes, DataIOError]:
    missing = _require_registry(ref, data_registry)
    if missing is not None:
        return Err(missing)
    parsed_result = _require_parsed_ref(ref)
    if parsed_result.is_err:
        return Err(parsed_result.unwrap_err())
    name, version = parsed_result.unwrap()

    finalize_result = data_registry.finalize_stream(name, version, now_fn())
    if finalize_result.is_err:
        return Err(_wrap_error(finalize_result.unwrap_err(), ref))
    return Ok(b"")


def _wrap_error(err: AxoError, ref: IORef) -> IOBackendError:
    """The one place a StorageError/core.errors AxoError crosses into a
    DataIOError. Deliberately a flat, non-branching wrap (no subtype ->
    subtype table) -- both transports stringify errors before they cross
    back to the worker, so nothing downstream branches on the specific
    subtype, only .code/.name of whatever crosses the wire matter, and
    that's IOBackendError's."""
    return IOBackendError(str(err), context={"location": ref.location, "kind": ref.kind})
