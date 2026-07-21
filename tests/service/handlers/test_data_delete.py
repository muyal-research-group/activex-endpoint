import pytest

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_shared.protocol import Command
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend
from axo_endpoint.service.handlers import DataDeleteHandler, DataRegisterHandler


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def registry(tmp_path, event_bus):
    return DataRegistry(
        catalog=InMemoryStorageBackend(),
        blob_backends={"fs": FilesystemStorageBackend(root=str(tmp_path))},
        event_bus=event_bus,
    )


def _register(registry, name="df1", version=1, total_size=8, chunk_bytes=4):
    DataRegisterHandler(registry=registry, own_rpc_uri="tcp://127.0.0.1:5555", now_fn=lambda: 100.0).handle(Command(
        operation="DATA_REGISTER", content_type="application/json",
        envelope={"name": name, "version": version, "total_size": total_size, "chunk_bytes": chunk_bytes},
    ))


def test_delete_removes_the_record(registry):
    _register(registry)
    handler = DataDeleteHandler(registry=registry, now_fn=lambda: 200.0)

    result = handler.handle(Command(
        operation="DATA_DELETE", content_type="application/json", envelope={"name": "df1", "version": 1},
    ))

    assert result.ok is True
    assert result.metadata == {"data_id": "df1", "version": 1}
    assert registry.status("df1", 1).registered is False


def test_delete_unregistered_returns_error(registry):
    handler = DataDeleteHandler(registry=registry, now_fn=lambda: 200.0)
    result = handler.handle(Command(
        operation="DATA_DELETE", content_type="application/json", envelope={"name": "missing", "version": 1},
    ))
    assert result.ok is False
    assert result.error_name == "STORAGE_ERROR"
    assert result.error_code == 4003


def test_missing_required_field_returns_error(registry):
    handler = DataDeleteHandler(registry=registry)
    result = handler.handle(
        Command(operation="DATA_DELETE", content_type="application/json", envelope={"name": "df1"})
    )
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
    assert result.error_code == 1001
