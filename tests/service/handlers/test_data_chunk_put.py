import pytest

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_shared.protocol import Command
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend
from axo_endpoint.service.handlers import DataChunkPutHandler


@pytest.fixture
def registry(tmp_path):
    reg = DataRegistry(
        catalog=InMemoryStorageBackend(),
        blob_backends={"fs": FilesystemStorageBackend(root=str(tmp_path))},
        event_bus=InMemoryEventBus(),
    )
    reg.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
    return reg


def _chunk_command(name="df1", version=1, chunk_index=0, payload=b"abcd"):
    return Command(
        operation="DATA_CHUNK_PUT",
        content_type="application/octet-stream",
        envelope={"name": name, "version": version, "chunk_index": chunk_index},
        payload=payload,
    )


def test_put_first_chunk_reports_incomplete(registry):
    handler = DataChunkPutHandler(registry=registry)
    result = handler.handle(_chunk_command(chunk_index=0, payload=b"abcd"))
    assert result.ok is True
    assert result.metadata == {"data_id": "df1", "version": 1, "received_count": 1, "total_chunks": 2, "complete": False}


def test_put_all_chunks_reports_complete(registry):
    handler = DataChunkPutHandler(registry=registry)
    handler.handle(_chunk_command(chunk_index=0, payload=b"abcd"))
    result = handler.handle(_chunk_command(chunk_index=1, payload=b"efgh"))
    assert result.metadata["complete"] is True
    assert registry.read_whole("df1", 1).unwrap() == b"abcdefgh"


def test_put_wrong_size_chunk_returns_error(registry):
    handler = DataChunkPutHandler(registry=registry)
    result = handler.handle(_chunk_command(chunk_index=0, payload=b"ab"))
    assert result.ok is False
    assert result.error_name == "CHUNK_SIZE_MISMATCH"


def test_put_chunk_for_unregistered_data_returns_error(registry):
    handler = DataChunkPutHandler(registry=registry)
    result = handler.handle(_chunk_command(name="missing", chunk_index=0, payload=b"abcd"))
    assert result.ok is False
    assert result.error_name == "DATA_NOT_REGISTERED"


def test_missing_field_returns_error(registry):
    handler = DataChunkPutHandler(registry=registry)
    result = handler.handle(Command(operation="DATA_CHUNK_PUT", content_type="application/octet-stream", envelope={}))
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
