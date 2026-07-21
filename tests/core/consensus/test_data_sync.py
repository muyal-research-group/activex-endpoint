import pytest

from axo_endpoint.core.consensus.data_sync import (
    DataRegistrySyncBridge,
    deserialize_data_record,
    is_data_tombstone,
    serialize_data_record,
    serialize_data_tombstone,
)
from axo_endpoint.core.consensus.dirty_tracker import DirtyTracker
from axo_endpoint.core.data import DATA_DELETED_EVENT, DATA_REGISTERED_EVENT, DataRecord, DataRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.storage import FilesystemStorageBackend, FsKey, InMemoryStorageBackend, StorageKey


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def catalog():
    return InMemoryStorageBackend()


@pytest.fixture
def registry(catalog, event_bus, tmp_path):
    return DataRegistry(
        catalog=catalog,
        blob_backends={"fs": FilesystemStorageBackend(root=str(tmp_path))},
        event_bus=event_bus,
    )


@pytest.fixture
def dirty_tracker():
    return DirtyTracker(max_dirty_count=50)


@pytest.fixture
def bridge(registry, catalog, dirty_tracker, event_bus):
    bridge = DataRegistrySyncBridge(
        registry=registry, catalog=catalog, dirty_tracker=dirty_tracker, now_fn=lambda: 42.0
    )
    event_bus.subscribe(DATA_REGISTERED_EVENT, bridge.on_data_event)
    event_bus.subscribe(DATA_DELETED_EVENT, bridge.on_data_deleted)
    return bridge


def test_on_data_event_marks_the_registered_key_dirty(registry, dirty_tracker, bridge):
    registry.register(name="df1", version=1, format="csv", kind="fs", total_size=8, chunk_bytes=4, now=1.0)

    mutation = dirty_tracker.drain()
    assert set(mutation.data_changes.keys()) == {"df1:1"}

    record = deserialize_data_record(mutation.data_changes["df1:1"])
    assert record.name == "df1"
    assert record.version == 1
    assert record.format == "csv"
    assert record.total_chunks == 2


def test_apply_incoming_writes_record_into_catalog_without_re_marking_dirty(bridge, catalog, dirty_tracker):
    record = DataRecord(
        name="df2", version=1, alias="df2", format="raw", kind="fs",
        total_size=5, chunk_bytes=4, total_chunks=2, created_at=5.0,
    )
    blob = serialize_data_record(record)
    bridge.apply_incoming({"df2:1": blob})

    stored = catalog.get(StorageKey(id="df2", version=1, alias="df2")).unwrap()
    assert stored == record

    # apply_incoming bypasses DataRegistry.register(), so no event fires and
    # the dirty tracker stays empty.
    mutation = dirty_tracker.drain()
    assert mutation.data_changes == {}


def test_on_data_deleted_marks_the_same_key_dirty_with_a_tombstone(registry, dirty_tracker, bridge):
    registry.register(name="df1", version=1, format="csv", kind="fs", total_size=8, chunk_bytes=4, now=1.0)
    dirty_tracker.drain()  # discard the registration's own dirty entry

    registry.delete("df1", 1, now=2.0)

    mutation = dirty_tracker.drain()
    assert set(mutation.data_changes.keys()) == {"df1:1"}
    assert is_data_tombstone(mutation.data_changes["df1:1"]) is True


def test_apply_incoming_tombstone_deletes_the_local_record_and_chunks(bridge, registry, catalog, tmp_path):
    registry.register(name="df2", version=1, format="raw", kind="fs", total_size=4, chunk_bytes=4, now=1.0)
    registry.store_chunk("df2", 1, 0, b"abcd")

    bridge.apply_incoming({"df2:1": serialize_data_tombstone()})

    assert catalog.get(StorageKey(id="df2", version=1, alias="df2")).unwrap() is None
    fs_backend = FilesystemStorageBackend(root=str(tmp_path))
    assert fs_backend.exists(FsKey(path="df2/1/chunk_00000000")).unwrap() is False


def test_apply_incoming_tombstone_for_a_never_replicated_key_is_not_an_error(bridge):
    # Nothing to delete locally -- the goal state (gone) is already
    # achieved, so this must not raise.
    bridge.apply_incoming({"never-seen:1": serialize_data_tombstone()})


def test_serialize_then_deserialize_round_trips_record():
    record = DataRecord(
        name="df3", version=2, alias="df3", format="npy", kind="fs",
        total_size=128, chunk_bytes=64, total_chunks=2, created_at=9.0,
        declared_hash="abc123",
    )
    blob = serialize_data_record(record)
    round_tripped = deserialize_data_record(blob)
    assert round_tripped == record
