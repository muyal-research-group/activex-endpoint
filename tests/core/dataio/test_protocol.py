import json

import pytest
from option import Err, Ok

from axo_endpoint.core.data import DATA_REGISTERED_EVENT, DataRegistry
from axo_endpoint.core.dataio import (
    APPEND_CHUNK,
    CHUNK_STATUS,
    FINALIZE_STREAM,
    OPEN_STREAM,
    READ,
    READ_CHUNK,
    WRITE,
    IORef,
    resolve_io_request,
)
from axo_endpoint.core.dataio.errors import IONotFoundError, UnknownIOOpError, UnknownIORefKindError
from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.storage import FilesystemStorageBackend, FsKey, InMemoryStorageBackend, StorageError


def test_resolve_read_delegates_to_correct_backend(tmp_path):
    backend = FilesystemStorageBackend(root=str(tmp_path))
    backend.put(FsKey(path="a.bin"), b"hello")
    ref = IORef(kind="fs", location="a.bin")

    result = resolve_io_request(READ, ref, None, {"fs": backend})
    assert result.is_ok
    assert result.unwrap() == b"hello"


def test_resolve_write_delegates_to_correct_backend(tmp_path):
    backend = FilesystemStorageBackend(root=str(tmp_path))
    ref = IORef(kind="fs", location="a.bin")

    result = resolve_io_request(WRITE, ref, b"world", {"fs": backend})
    assert result.is_ok
    assert backend.get(FsKey(path="a.bin")).unwrap() == b"world"


def test_resolve_unknown_kind_returns_err(tmp_path):
    ref = IORef(kind="s3", location="a.bin")
    result = resolve_io_request(READ, ref, None, {"fs": FilesystemStorageBackend(root=str(tmp_path))})
    assert result.is_err
    assert isinstance(result.unwrap_err(), UnknownIORefKindError)


def test_resolve_unknown_op_returns_err(tmp_path):
    ref = IORef(kind="fs", location="a.bin")
    result = resolve_io_request("delete", ref, None, {"fs": FilesystemStorageBackend(root=str(tmp_path))})
    assert result.is_err
    assert isinstance(result.unwrap_err(), UnknownIOOpError)


def test_resolve_read_missing_translates_ok_none_to_not_found(tmp_path):
    # StorageBackend.get() returns Ok(None) for "not found" -- resolve_io_request
    # is the one place that gets translated into a loud read failure, since
    # dataio.read() must not silently return None to a job.
    backend = FilesystemStorageBackend(root=str(tmp_path))
    ref = IORef(kind="fs", location="missing.bin")
    result = resolve_io_request(READ, ref, None, {"fs": backend})
    assert result.is_err
    assert isinstance(result.unwrap_err(), IONotFoundError)


class _AlwaysOkNoneBackend:
    """Fake StorageBackend whose get() returns Ok(None) directly, isolating
    the Ok(None) -> IONotFoundError translation from any filesystem-specific
    behavior that might otherwise mask it."""

    def get(self, key):
        return Ok(None)

    def put(self, key, value):
        return Ok("")

    def exists(self, key):
        return Ok(False)


def test_resolve_read_ok_none_translation_is_isolated_from_backend_specifics():
    ref = IORef(kind="fake", location="anything")
    from axo_endpoint.core.dataio import protocol

    original_key_types = dict(protocol.KEY_TYPES)
    protocol.KEY_TYPES["fake"] = protocol.KEY_TYPES["fs"]
    try:
        result = resolve_io_request(READ, ref, None, {"fake": _AlwaysOkNoneBackend()})
        assert result.is_err
        assert isinstance(result.unwrap_err(), IONotFoundError)
    finally:
        protocol.KEY_TYPES.clear()
        protocol.KEY_TYPES.update(original_key_types)


@pytest.fixture
def blob_backend(tmp_path):
    return FilesystemStorageBackend(root=str(tmp_path))


@pytest.fixture
def data_registry(blob_backend):
    return DataRegistry(
        catalog=InMemoryStorageBackend(), blob_backends={"fs": blob_backend}, event_bus=InMemoryEventBus(),
    )


def test_resolve_read_reconstructs_registered_data_from_chunks(blob_backend, data_registry):
    data_registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
    data_registry.store_chunk("df1", 1, 0, b"abcd")
    data_registry.store_chunk("df1", 1, 1, b"efgh")

    ref = IORef(kind="fs", location="df1/1")
    result = resolve_io_request(READ, ref, None, {"fs": blob_backend}, data_registry)
    assert result.is_ok
    assert result.unwrap() == b"abcdefgh"


def test_resolve_read_falls_back_to_ad_hoc_blob_when_not_registered(blob_backend, data_registry):
    # A location that isn't a registered (name, version) -- e.g. an ordinary
    # dataio.write() output -- must be unaffected by DataRegistry existing.
    blob_backend.put(FsKey(path="in.csv"), b"a,b\n1,2\n")
    ref = IORef(kind="fs", location="in.csv")
    result = resolve_io_request(READ, ref, None, {"fs": blob_backend}, data_registry)
    assert result.is_ok
    assert result.unwrap() == b"a,b\n1,2\n"


def test_resolve_chunk_status_returns_total_chunks_and_chunk_bytes(data_registry):
    data_registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
    ref = IORef(kind="fs", location="df1/1")
    result = resolve_io_request(CHUNK_STATUS, ref, None, {}, data_registry)
    assert result.is_ok
    assert json.loads(result.unwrap().decode("utf-8")) == {"total_chunks": 2, "chunk_bytes": 4}


def test_resolve_chunk_status_unregistered_returns_not_found(data_registry):
    ref = IORef(kind="fs", location="missing/1")
    result = resolve_io_request(CHUNK_STATUS, ref, None, {}, data_registry)
    assert result.is_err
    assert isinstance(result.unwrap_err(), IONotFoundError)


def test_resolve_read_chunk_returns_one_chunk(data_registry):
    data_registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
    data_registry.store_chunk("df1", 1, 0, b"abcd")
    data_registry.store_chunk("df1", 1, 1, b"efgh")

    ref = IORef(kind="fs", location="df1/1", chunk_index=1)
    result = resolve_io_request(READ_CHUNK, ref, None, {}, data_registry)
    assert result.is_ok
    assert result.unwrap() == b"efgh"


def test_resolve_read_chunk_without_chunk_index_errors(data_registry):
    data_registry.register(name="df1", version=1, format="raw", kind="fs", total_size=4, chunk_bytes=4, now=100.0)
    ref = IORef(kind="fs", location="df1/1")
    result = resolve_io_request(READ_CHUNK, ref, None, {}, data_registry)
    assert result.is_err


def test_resolve_open_append_finalize_stream_round_trip(data_registry, blob_backend):
    received = []
    data_registry._event_bus.subscribe(DATA_REGISTERED_EVENT, received.append)

    ref = IORef(kind="fs", location="out1/1", format="raw")
    open_result = resolve_io_request(
        OPEN_STREAM, ref, json.dumps({"chunk_bytes": 4}).encode("utf-8"), {"fs": blob_backend}, data_registry,
    )
    assert open_result.is_ok
    assert received == []  # open must not register/replicate yet

    resolve_io_request(APPEND_CHUNK, ref, b"abcd", {"fs": blob_backend}, data_registry)
    resolve_io_request(APPEND_CHUNK, ref, b"ef", {"fs": blob_backend}, data_registry)

    finalize_result = resolve_io_request(FINALIZE_STREAM, ref, None, {"fs": blob_backend}, data_registry)
    assert finalize_result.is_ok
    assert len(received) == 1

    read_result = resolve_io_request(READ, ref, None, {"fs": blob_backend}, data_registry)
    assert read_result.unwrap() == b"abcdef"


def test_resolve_chunk_ops_without_data_registry_return_err():
    ref = IORef(kind="fs", location="df1/1")
    for op, data in [
        (CHUNK_STATUS, None),
        (READ_CHUNK, None),
        (OPEN_STREAM, None),
        (APPEND_CHUNK, b"x"),
        (FINALIZE_STREAM, None),
    ]:
        result = resolve_io_request(op, ref, data, {}, None)
        assert result.is_err, op
