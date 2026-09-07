from types import SimpleNamespace

import pytest

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_shared.protocol import Command
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend
from axo_endpoint.service.handlers import DataInfoHandler


class _FakeReplicator:
    """Duck-typed stand-in for BlobReplicator -- only peer_status_for matters
    to DataInfoHandler, so the handler test doesn't need to depend on the
    real replicator's tick-driven cache-population logic."""

    def __init__(self, peer_status):
        self._peer_status = peer_status

    def peer_status_for(self, name, version):
        return self._peer_status.get((name, version), {})


@pytest.fixture
def registry(tmp_path):
    reg = DataRegistry(
        catalog=InMemoryStorageBackend(),
        blob_backends={"fs": FilesystemStorageBackend(root=str(tmp_path))},
        event_bus=InMemoryEventBus(),
    )
    reg.register(
        name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0,
        content_hash="deadbeef",
    )
    reg.store_chunk("df1", 1, 0, b"abcd")
    reg.store_chunk("df1", 1, 1, b"efgh")
    return reg


def _info_command(name="df1", version=1):
    return Command(operation="DATA_INFO", content_type="application/json", envelope={"name": name, "version": version})


def test_info_aggregates_status_and_hash_fields(registry):
    replicator = _FakeReplicator({})
    handler = DataInfoHandler(registry=registry, replicator=replicator)

    result = handler.handle(_info_command())

    assert result.ok is True
    assert result.metadata["total_chunks"] == 2
    assert result.metadata["progress_ratio"] == 1.0
    assert result.metadata["declared_hash"] == "deadbeef"
    assert result.metadata["computed_hash"] is not None
    assert result.metadata["hash_verified"] is False  # declared_hash is a fake value, doesn't match
    assert result.metadata["replica_count"] == 0
    assert result.metadata["replicas"] == []


def test_info_replica_count_counts_only_complete_peers(registry):
    peer_status = {
        ("df1", 1): {
            "node-b": SimpleNamespace(complete=True, present_chunks=2, total_chunks=2, latency_ms=5.0, last_synced_at=100.0),
            "node-c": SimpleNamespace(complete=False, present_chunks=1, total_chunks=2, latency_ms=8.0, last_synced_at=99.0),
        }
    }
    replicator = _FakeReplicator(peer_status)
    handler = DataInfoHandler(registry=registry, replicator=replicator)

    result = handler.handle(_info_command())

    assert result.metadata["replica_count"] == 1
    assert len(result.metadata["replicas"]) == 2
    by_peer = {r["peer_id"]: r for r in result.metadata["replicas"]}
    assert by_peer["node-b"]["complete"] is True
    assert by_peer["node-c"]["complete"] is False


def test_missing_field_returns_error(registry):
    handler = DataInfoHandler(registry=registry, replicator=_FakeReplicator({}))
    result = handler.handle(Command(operation="DATA_INFO", content_type="application/json", envelope={}))
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
