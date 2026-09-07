import pytest

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_shared.protocol import Command
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend
from axo_endpoint.service.handlers import DataChunkGetHandler, DataChunkPutHandler, DataRegisterHandler


@pytest.fixture
def registry(tmp_path):
    return DataRegistry(
        catalog=InMemoryStorageBackend(),
        blob_backends={"fs": FilesystemStorageBackend(root=str(tmp_path))},
        event_bus=InMemoryEventBus(),
    )


def _register_and_store(registry, name="df1", version=1, chunks=(b"abcd", b"efgh")):
    DataRegisterHandler(registry=registry, own_rpc_uri="tcp://127.0.0.1:5555").handle(Command(
        operation="DATA_REGISTER", content_type="application/json",
        envelope={
            "name": name, "version": version,
            "total_size": sum(len(c) for c in chunks), "chunk_bytes": len(chunks[0]),
        },
    ))
    put_handler = DataChunkPutHandler(registry=registry)
    for i, chunk in enumerate(chunks):
        put_handler.handle(Command(
            operation="DATA_CHUNK_PUT", content_type="application/octet-stream",
            envelope={"name": name, "version": version, "chunk_index": i}, payload=chunk,
        ))


def test_read_a_stored_chunk_returns_its_bytes(registry):
    _register_and_store(registry)
    handler = DataChunkGetHandler(registry=registry)

    result = handler.handle(Command(
        operation="DATA_CHUNK_GET", content_type="application/json",
        envelope={"name": "df1", "version": 1, "chunk_index": 1},
    ))

    assert result.ok is True
    assert result.payload == b"efgh"
    assert result.metadata == {"name": "df1", "version": 1, "chunk_index": 1}


def test_read_unregistered_data_returns_error(registry):
    handler = DataChunkGetHandler(registry=registry)
    result = handler.handle(Command(
        operation="DATA_CHUNK_GET", content_type="application/json",
        envelope={"name": "missing", "version": 1, "chunk_index": 0},
    ))
    assert result.ok is False
    assert result.error_code == 4003


def test_read_a_chunk_never_stored_returns_error(registry):
    DataRegisterHandler(registry=registry, own_rpc_uri="tcp://127.0.0.1:5555").handle(Command(
        operation="DATA_REGISTER", content_type="application/json",
        envelope={"name": "df1", "version": 1, "total_size": 8, "chunk_bytes": 4},
    ))
    handler = DataChunkGetHandler(registry=registry)
    result = handler.handle(Command(
        operation="DATA_CHUNK_GET", content_type="application/json",
        envelope={"name": "df1", "version": 1, "chunk_index": 0},
    ))
    assert result.ok is False


def test_missing_required_field_returns_error(registry):
    handler = DataChunkGetHandler(registry=registry)
    result = handler.handle(Command(
        operation="DATA_CHUNK_GET", content_type="application/json", envelope={"name": "df1", "version": 1},
    ))
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
    assert result.error_code == 1001
