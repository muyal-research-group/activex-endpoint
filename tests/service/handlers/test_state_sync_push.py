import pytest

from axo_endpoint.core.consensus.bucket_sync import BucketRegistrySyncBridge, serialize_data_bucket
from axo_endpoint.core.consensus.data_sync import DataRegistrySyncBridge, serialize_data_record, serialize_data_tombstone
from axo_endpoint.core.consensus.dirty_tracker import DirtyTracker
from axo_endpoint.core.consensus.registry_sync import RegistrySyncBridge, serialize_function_record
from axo_endpoint.core.consensus.state_machine import ClusterState, InMemoryReplicatedStateMachine, encode_state_changes
from axo_endpoint.core.data import DataBucket, DataRecord, DataRegistry
from axo_endpoint.core.data.bucket_registry import BucketRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.functions.lifecycle import FunctionState
from axo_shared.functions.models import FunctionRecord
from axo_shared.protocol import Command
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend, StorageKey
from axo_endpoint.service.handlers.state_sync_push import StateSyncPushHandler


@pytest.fixture
def backend():
    return InMemoryStorageBackend()


@pytest.fixture
def registry_sync(backend):
    registry = FunctionRegistry(backend=backend, event_bus=InMemoryEventBus())
    return RegistrySyncBridge(registry=registry, backend=backend, dirty_tracker=DirtyTracker(max_dirty_count=50))


@pytest.fixture
def data_catalog():
    return InMemoryStorageBackend()


@pytest.fixture
def data_registry_sync(data_catalog, tmp_path):
    registry = DataRegistry(
        catalog=data_catalog,
        blob_backends={"fs": FilesystemStorageBackend(root=str(tmp_path))},
        event_bus=InMemoryEventBus(),
    )
    return DataRegistrySyncBridge(registry=registry, catalog=data_catalog, dirty_tracker=DirtyTracker(max_dirty_count=50))


@pytest.fixture
def bucket_catalog():
    return InMemoryStorageBackend()


@pytest.fixture
def bucket_registry_sync(bucket_catalog):
    registry = BucketRegistry(catalog=bucket_catalog, event_bus=InMemoryEventBus())
    return BucketRegistrySyncBridge(
        registry=registry, catalog=bucket_catalog, dirty_tracker=DirtyTracker(max_dirty_count=50),
    )


@pytest.fixture
def state_machine():
    return InMemoryReplicatedStateMachine()


@pytest.fixture
def handler(state_machine, registry_sync, data_registry_sync, bucket_registry_sync):
    return StateSyncPushHandler(
        state_machine=state_machine, registry_sync=registry_sync, data_registry_sync=data_registry_sync,
        bucket_registry_sync=bucket_registry_sync,
    )


def _record(name="foo", version=1):
    return FunctionRecord(
        code=b"print(1)", function_id=name, name=name, version=version, created_at=1.0,
        state=FunctionState.REGISTERED, runtime_spec=None,
    )


def _data_record(name="bar", version=1):
    return DataRecord(
        name=name, version=version, alias=name, format="raw", kind="fs",
        total_size=3, chunk_bytes=4, total_chunks=1, created_at=1.0,
    )


def _bucket(name="mybucket"):
    return DataBucket(name=name, quota_bytes=1024, created_at=1.0)


def _push_command(term, function_changes=None, data_changes=None, bucket_changes=None):
    return Command(
        operation="STATE_SYNC_PUSH",
        content_type="application/json",
        envelope={"term": term, "leader_ids": ["leader"], "members": ["leader", "self"]},
        payload=encode_state_changes(function_changes or {}, data_changes or {}, bucket_changes or {}),
    )


def test_higher_term_push_applies(handler, state_machine, backend):
    record = _record()
    changes = {"foo:1": serialize_function_record(record)}

    result = handler.handle(_push_command(term=1, function_changes=changes))

    assert result.ok is True
    assert state_machine.snapshot().term == 1
    assert state_machine.snapshot().leader_ids == frozenset({"leader"})


def test_pushed_function_data_lands_in_the_backend(handler, backend):
    record = _record(name="bar", version=2)
    changes = {"bar:2": serialize_function_record(record)}

    handler.handle(_push_command(term=1, function_changes=changes))

    stored = backend.get(StorageKey(id="bar", version=2, alias="bar")).unwrap()
    assert stored == record


def test_pushed_data_record_lands_in_the_data_catalog(handler, data_catalog):
    record = _data_record(name="df1", version=1)
    changes = {"df1:1": serialize_data_record(record)}

    handler.handle(_push_command(term=1, data_changes=changes))

    stored = data_catalog.get(StorageKey(id="df1", version=1, alias="df1")).unwrap()
    assert stored == record


def test_data_only_push_with_no_function_changes_still_applies(handler, state_machine, data_catalog):
    # Regression guard for the event-topic-collision/early-return class of
    # bugs: a push carrying only data_changes (no function_changes at all)
    # must still bump local state and land in the data catalog.
    record = _data_record(name="df2", version=1)
    changes = {"df2:1": serialize_data_record(record)}

    result = handler.handle(_push_command(term=1, data_changes=changes))

    assert result.ok is True
    assert state_machine.snapshot().data == {"df2:1": serialize_data_record(record)}
    assert data_catalog.get(StorageKey(id="df2", version=1, alias="df2")).unwrap() == record


def test_pushed_tombstone_removes_an_existing_data_record_from_the_catalog(handler, data_catalog):
    record = _data_record(name="df3", version=1)
    handler.handle(_push_command(term=1, data_changes={"df3:1": serialize_data_record(record)}))
    assert data_catalog.get(StorageKey(id="df3", version=1, alias="df3")).unwrap() == record

    result = handler.handle(_push_command(term=2, data_changes={"df3:1": serialize_data_tombstone()}))

    assert result.ok is True
    assert data_catalog.get(StorageKey(id="df3", version=1, alias="df3")).unwrap() is None


def test_pushed_bucket_lands_in_the_bucket_catalog(handler, bucket_catalog):
    bucket = _bucket(name="mybucket")
    changes = {"mybucket": serialize_data_bucket(bucket)}

    handler.handle(_push_command(term=1, bucket_changes=changes))

    stored = bucket_catalog.get(StorageKey(id="mybucket")).unwrap()
    assert stored == bucket


def test_stale_term_push_is_rejected_and_state_unchanged(
    state_machine, registry_sync, data_registry_sync, bucket_registry_sync,
):
    # Bump local state to term=5 first.
    state_machine.apply_remote(ClusterState(term=5, leader_ids=frozenset({"leader"}), version=1))
    handler = StateSyncPushHandler(
        state_machine=state_machine, registry_sync=registry_sync, data_registry_sync=data_registry_sync,
        bucket_registry_sync=bucket_registry_sync,
    )

    changes = {"foo:1": serialize_function_record(_record())}
    result = handler.handle(_push_command(term=1, function_changes=changes))

    assert result.ok is False
    assert result.error_code == 6002
    assert result.error_name == "STALE_TERM"
    assert state_machine.snapshot().term == 5
    assert state_machine.snapshot().functions == {}
