import pytest

from axo_endpoint.core.data import BucketRegistry, DataRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_shared.protocol import Command
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend
from axo_endpoint.service.handlers import DataRegisterHandler


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


@pytest.fixture
def bucket_registry(event_bus):
    return BucketRegistry(catalog=InMemoryStorageBackend(), event_bus=event_bus)


def test_register_returns_metadata_and_leader_rpc_uri(registry):
    handler = DataRegisterHandler(registry=registry, own_rpc_uri="tcp://127.0.0.1:5555", now_fn=lambda: 100.0)
    command = Command(
        operation="DATA_REGISTER",
        content_type="application/json",
        envelope={"name": "df1", "version": 1, "format": "csv", "total_size": 8, "chunk_bytes": 4},
    )

    result = handler.handle(command)

    assert result.ok is True
    assert result.metadata == {
        "data_id": "df1", "version": 1, "kind": "fs", "format": "csv",
        "total_size": 8, "chunk_bytes": 4, "total_chunks": 2,
        "leader_rpc_uri": "tcp://127.0.0.1:5555",
    }


def test_register_defaults_format_and_kind(registry):
    handler = DataRegisterHandler(registry=registry, own_rpc_uri="tcp://127.0.0.1:5555", now_fn=lambda: 100.0)
    command = Command(
        operation="DATA_REGISTER",
        content_type="application/json",
        envelope={"name": "df1", "version": 1, "total_size": 4, "chunk_bytes": 4},
    )

    result = handler.handle(command)

    assert result.ok is True
    assert result.metadata["kind"] == "fs"
    assert result.metadata["format"] == "raw"


def test_register_with_content_hash_is_declared(registry):
    handler = DataRegisterHandler(registry=registry, own_rpc_uri="tcp://127.0.0.1:5555", now_fn=lambda: 100.0)
    command = Command(
        operation="DATA_REGISTER",
        content_type="application/json",
        envelope={"name": "df1", "version": 1, "total_size": 4, "chunk_bytes": 4, "content_hash": "abc123"},
    )

    handler.handle(command)

    record = registry.status("df1", 1)
    assert record.declared_hash == "abc123"


def test_missing_required_field_returns_error(registry):
    handler = DataRegisterHandler(registry=registry, own_rpc_uri="tcp://127.0.0.1:5555")
    result = handler.handle(
        Command(operation="DATA_REGISTER", content_type="application/json", envelope={"name": "df1", "version": 1})
    )
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
    assert result.error_code == 1001


def test_namespaced_register_into_unknown_bucket_is_rejected(registry, bucket_registry):
    handler = DataRegisterHandler(
        registry=registry, own_rpc_uri="tcp://127.0.0.1:5555", bucket_registry=bucket_registry,
    )
    result = handler.handle(Command(
        operation="DATA_REGISTER", content_type="application/json",
        envelope={"name": "mybucket/df1", "version": 1, "total_size": 4, "chunk_bytes": 4},
    ))
    assert result.ok is False
    assert result.error_name == "BUCKET_NOT_FOUND"


def test_namespaced_register_within_quota_succeeds(registry, bucket_registry):
    bucket_registry.register(name="mybucket", quota_bytes=100, now=0.0)
    handler = DataRegisterHandler(
        registry=registry, own_rpc_uri="tcp://127.0.0.1:5555", bucket_registry=bucket_registry,
    )
    result = handler.handle(Command(
        operation="DATA_REGISTER", content_type="application/json",
        envelope={"name": "mybucket/df1", "version": 1, "total_size": 40, "chunk_bytes": 40},
    ))
    assert result.ok is True


def test_namespaced_register_exceeding_quota_is_rejected(registry, bucket_registry):
    bucket_registry.register(name="mybucket", quota_bytes=50, now=0.0)
    handler = DataRegisterHandler(
        registry=registry, own_rpc_uri="tcp://127.0.0.1:5555", bucket_registry=bucket_registry,
    )
    handler.handle(Command(
        operation="DATA_REGISTER", content_type="application/json",
        envelope={"name": "mybucket/df1", "version": 1, "total_size": 40, "chunk_bytes": 40},
    ))

    result = handler.handle(Command(
        operation="DATA_REGISTER", content_type="application/json",
        envelope={"name": "mybucket/df2", "version": 1, "total_size": 20, "chunk_bytes": 20},
    ))
    assert result.ok is False
    assert result.error_name == "QUOTA_EXCEEDED"


def test_unnamespaced_register_skips_bucket_check_entirely(registry, bucket_registry):
    """Backward compatibility: a name with no "/" is never bucket/quota
    checked, even when a bucket_registry is wired in -- existing non-bucket
    DATA_REGISTER callers (tests, CLI, examples) are unaffected."""
    handler = DataRegisterHandler(
        registry=registry, own_rpc_uri="tcp://127.0.0.1:5555", bucket_registry=bucket_registry,
    )
    result = handler.handle(Command(
        operation="DATA_REGISTER", content_type="application/json",
        envelope={"name": "df1", "version": 1, "total_size": 4, "chunk_bytes": 4},
    ))
    assert result.ok is True
