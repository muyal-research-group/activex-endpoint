import pytest

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_shared.protocol import Command
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend
from axo_endpoint.service.handlers import DataStatusHandler


@pytest.fixture
def registry(tmp_path):
    return DataRegistry(
        catalog=InMemoryStorageBackend(),
        blob_backends={"fs": FilesystemStorageBackend(root=str(tmp_path))},
        event_bus=InMemoryEventBus(),
    )


def _status_command(name="df1", version=1):
    return Command(operation="DATA_STATUS", content_type="application/json", envelope={"name": name, "version": version})


def test_status_of_unregistered_reports_not_registered(registry):
    handler = DataStatusHandler(registry=registry)
    result = handler.handle(_status_command())
    assert result.ok is True
    assert result.metadata["registered"] is False


def test_status_reports_present_chunks(registry):
    registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
    registry.store_chunk("df1", 1, 0, b"abcd")

    handler = DataStatusHandler(registry=registry)
    result = handler.handle(_status_command())

    assert result.metadata["registered"] is True
    assert result.metadata["present_chunk_indices"] == [0]
    assert result.metadata["total_chunks"] == 2
    assert result.metadata["complete"] is False


def test_missing_field_returns_error(registry):
    handler = DataStatusHandler(registry=registry)
    result = handler.handle(Command(operation="DATA_STATUS", content_type="application/json", envelope={}))
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
