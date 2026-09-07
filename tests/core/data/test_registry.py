import pytest

from axo_endpoint.core.data import DATA_DELETED_EVENT, DATA_REGISTERED_EVENT, DATA_UPLOAD_COMPLETED_EVENT, DataRegistry
from axo_endpoint.core.dataio.errors import UnknownIORefKindError
from axo_endpoint.core.errors import (
    ChunkIndexOutOfRangeError,
    ChunkSizeMismatchError,
    DataNotRegisteredError,
    StreamAlreadyFinalizedError,
    StreamNotOpenError,
)
from axo_endpoint.core.events import Event, InMemoryEventBus
from axo_endpoint.core.storage import FilesystemStorageBackend, FsKey, InMemoryStorageBackend, StorageKey


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def catalog():
    return InMemoryStorageBackend()


@pytest.fixture
def blob_backend(tmp_path):
    return FilesystemStorageBackend(root=str(tmp_path))


@pytest.fixture
def registry(catalog, blob_backend, event_bus):
    return DataRegistry(catalog=catalog, blob_backends={"fs": blob_backend}, event_bus=event_bus)


def test_register_writes_metadata_only_no_bytes(registry, blob_backend):
    result = registry.register(name="df1", version=1, format="csv", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
    assert result.is_ok
    record = result.unwrap()
    assert record.total_chunks == 2
    assert blob_backend.exists(FsKey(path="df1/1/chunk_00000000")).unwrap() is False


def test_register_then_get_round_trips_record(registry):
    registry.register(name="df1", version=1, format="csv", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
    record = registry.get(StorageKey(id="df1", version=1, alias="df1")).unwrap()
    assert record.name == "df1"
    assert record.version == 1
    assert record.format == "csv"
    assert record.kind == "fs"
    assert record.total_size == 8
    assert record.chunk_bytes == 4
    assert record.total_chunks == 2
    assert record.created_at == 100.0


def test_register_emits_data_registered_event_with_total_chunks(registry, event_bus):
    received = []
    event_bus.subscribe(DATA_REGISTERED_EVENT, received.append)

    registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)

    assert received == [
        Event(
            event_type=DATA_REGISTERED_EVENT,
            payload={
                "data_id": "df1", "version": 1, "total_chunks": 2,
                "format": "raw", "kind": "fs", "total_size": 8,
            },
            timestamp=100.0,
        )
    ]


def test_get_on_nonexistent_key_returns_ok_none(registry):
    result = registry.get(StorageKey(id="missing"))
    assert result.is_ok
    assert result.unwrap() is None


def test_register_unknown_kind_returns_err(registry):
    result = registry.register(name="df1", version=1, format="raw", kind="s3", total_size=1, chunk_bytes=4, now=100.0)
    assert result.is_err
    assert isinstance(result.unwrap_err(), UnknownIORefKindError)


def test_register_with_content_hash_is_stored_declared(registry):
    record = registry.register(
        name="df1", version=1, format="raw", kind="fs", total_size=4, chunk_bytes=4, now=100.0,
        content_hash="deadbeef",
    ).unwrap()
    assert record.declared_hash == "deadbeef"


class TestStoreChunkAndRead:
    def test_store_chunk_then_read_whole_reassembles(self, registry):
        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
        assert registry.store_chunk("df1", 1, 0, b"abcd").is_ok
        assert registry.store_chunk("df1", 1, 1, b"efgh").is_ok
        assert registry.read_whole("df1", 1).unwrap() == b"abcdefgh"

    def test_last_chunk_emits_upload_completed_event(self, registry, event_bus):
        received = []
        event_bus.subscribe(DATA_UPLOAD_COMPLETED_EVENT, received.append)

        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
        registry.store_chunk("df1", 1, 0, b"abcd", now=101.0)
        assert received == []
        registry.store_chunk("df1", 1, 1, b"efgh", now=102.0)

        assert received == [
            Event(
                event_type=DATA_UPLOAD_COMPLETED_EVENT,
                payload={"data_id": "df1", "version": 1},
                timestamp=102.0,
            )
        ]

    def test_re_storing_last_chunk_does_not_re_emit_completed_event(self, registry, event_bus):
        received = []
        event_bus.subscribe(DATA_UPLOAD_COMPLETED_EVENT, received.append)

        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
        registry.store_chunk("df1", 1, 0, b"abcd")
        registry.store_chunk("df1", 1, 1, b"efgh")
        registry.store_chunk("df1", 1, 1, b"efgh")  # duplicate/retried PUT of the same last chunk

        assert len(received) == 1

    def test_zero_size_register_emits_completed_event_immediately(self, registry, event_bus):
        received = []
        event_bus.subscribe(DATA_UPLOAD_COMPLETED_EVENT, received.append)

        registry.register(name="empty", version=1, format="raw", kind="fs", total_size=0, chunk_bytes=4, now=100.0)

        assert received == [
            Event(
                event_type=DATA_UPLOAD_COMPLETED_EVENT,
                payload={"data_id": "empty", "version": 1},
                timestamp=100.0,
            )
        ]

    def test_store_chunk_out_of_range_index_errors(self, registry):
        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
        result = registry.store_chunk("df1", 1, 2, b"abcd")
        assert result.is_err
        assert isinstance(result.unwrap_err(), ChunkIndexOutOfRangeError)

    def test_store_chunk_wrong_size_errors(self, registry):
        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
        result = registry.store_chunk("df1", 1, 0, b"ab")
        assert result.is_err
        assert isinstance(result.unwrap_err(), ChunkSizeMismatchError)

    def test_store_chunk_last_chunk_allows_shorter_remainder(self, registry):
        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=6, chunk_bytes=4, now=100.0)
        assert registry.store_chunk("df1", 1, 0, b"abcd").is_ok
        assert registry.store_chunk("df1", 1, 1, b"ef").is_ok
        assert registry.read_whole("df1", 1).unwrap() == b"abcdef"

    def test_store_chunk_without_register_errors(self, registry):
        result = registry.store_chunk("missing", 1, 0, b"x")
        assert result.is_err
        assert isinstance(result.unwrap_err(), DataNotRegisteredError)

    def test_read_chunk_before_stored_errors(self, registry):
        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=4, chunk_bytes=4, now=100.0)
        result = registry.read_chunk("df1", 1, 0)
        assert result.is_err


class TestDelete:
    def test_delete_removes_catalog_entry_and_chunks(self, registry, blob_backend):
        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
        registry.store_chunk("df1", 1, 0, b"abcd")
        registry.store_chunk("df1", 1, 1, b"efgh")

        result = registry.delete("df1", 1, now=200.0)
        assert result.is_ok
        assert registry.get(StorageKey(id="df1", version=1, alias="df1")).unwrap() is None
        assert blob_backend.exists(FsKey(path="df1/1/chunk_00000000")).unwrap() is False
        assert blob_backend.exists(FsKey(path="df1/1/chunk_00000001")).unwrap() is False

    def test_delete_unregistered_errors(self, registry):
        result = registry.delete("missing", 1, now=100.0)
        assert result.is_err
        assert isinstance(result.unwrap_err(), DataNotRegisteredError)

    def test_delete_emits_data_deleted_event(self, registry, event_bus):
        received = []
        event_bus.subscribe(DATA_DELETED_EVENT, received.append)

        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=4, chunk_bytes=4, now=100.0)
        registry.store_chunk("df1", 1, 0, b"abcd")
        registry.delete("df1", 1, now=200.0)

        assert received == [
            Event(event_type=DATA_DELETED_EVENT, payload={"data_id": "df1", "version": 1}, timestamp=200.0)
        ]

    def test_delete_before_any_chunk_stored_still_works(self, registry):
        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
        result = registry.delete("df1", 1, now=200.0)
        assert result.is_ok

    def test_re_register_after_delete_does_not_reuse_stale_completion_state(self, registry, event_bus):
        """A re-registered df1:1 must be able to reach "complete" again --
        delete() must clear the _completed_uploads guard, not just the
        catalog entry, or the second upload's last chunk would silently
        never re-fire DATA_UPLOAD_COMPLETED_EVENT."""
        from axo_endpoint.core.data import DATA_UPLOAD_COMPLETED_EVENT

        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=4, chunk_bytes=4, now=100.0)
        registry.store_chunk("df1", 1, 0, b"abcd")
        registry.delete("df1", 1, now=150.0)

        received = []
        event_bus.subscribe(DATA_UPLOAD_COMPLETED_EVENT, received.append)
        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=4, chunk_bytes=4, now=200.0)
        registry.store_chunk("df1", 1, 0, b"wxyz")

        assert len(received) == 1


class TestStatus:
    def test_status_of_unregistered_is_not_registered(self, registry):
        status = registry.status("missing", 1)
        assert status.registered is False
        assert status.complete is False

    def test_status_reports_progress_before_complete(self, registry):
        registry.register(name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0)
        registry.store_chunk("df1", 1, 0, b"abcd")
        status = registry.status("df1", 1)
        assert status.present_chunk_indices == [0]
        assert status.complete is False
        assert status.progress_ratio == 0.5
        assert status.computed_hash is None

    def test_status_complete_computes_and_caches_hash(self, registry):
        registry.register(
            name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0,
            content_hash=None,
        )
        registry.store_chunk("df1", 1, 0, b"abcd")
        registry.store_chunk("df1", 1, 1, b"efgh")

        first = registry.status("df1", 1)
        assert first.complete is True
        assert first.computed_hash is not None

        second = registry.status("df1", 1)
        assert second.computed_hash == first.computed_hash

    def test_status_hash_verified_true_when_declared_matches(self, registry):
        import hashlib

        digest = hashlib.sha256(b"abcdefgh").hexdigest()
        registry.register(
            name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0,
            content_hash=digest,
        )
        registry.store_chunk("df1", 1, 0, b"abcd")
        registry.store_chunk("df1", 1, 1, b"efgh")
        status = registry.status("df1", 1)
        assert status.hash_verified is True

    def test_status_hash_verified_false_when_declared_mismatches(self, registry):
        registry.register(
            name="df1", version=1, format="raw", kind="fs", total_size=8, chunk_bytes=4, now=100.0,
            content_hash="not-the-real-hash",
        )
        registry.store_chunk("df1", 1, 0, b"abcd")
        registry.store_chunk("df1", 1, 1, b"efgh")
        status = registry.status("df1", 1)
        assert status.hash_verified is False

    def test_status_zero_size_record_is_complete_with_no_chunks(self, registry):
        registry.register(name="empty", version=1, format="raw", kind="fs", total_size=0, chunk_bytes=4, now=100.0)
        status = registry.status("empty", 1)
        assert status.total_chunks == 0
        assert status.complete is True
        assert status.progress_ratio == 1.0


class TestRegisterAndStore:
    def test_register_and_store_whole_blob_matches_manual_loop(self, registry):
        record = registry.register_and_store(
            name="df1", version=1, format="raw", kind="fs", data=b"abcdefgh", now=100.0, chunk_bytes=4,
        ).unwrap()
        assert record.total_chunks == 2
        assert registry.read_whole("df1", 1).unwrap() == b"abcdefgh"


class TestStreamingWrite:
    def test_open_stream_does_not_touch_catalog_or_emit_event(self, registry, event_bus):
        received = []
        event_bus.subscribe(DATA_REGISTERED_EVENT, received.append)

        registry.open_stream("out1", 1, format="raw", kind="fs", chunk_bytes=4)

        assert registry.get(StorageKey(id="out1", version=1, alias="out1")).unwrap() is None
        assert received == []

    def test_append_then_finalize_registers_and_emits_event(self, registry, event_bus):
        received = []
        event_bus.subscribe(DATA_REGISTERED_EVENT, received.append)

        registry.open_stream("out1", 1, format="raw", kind="fs", chunk_bytes=4)
        assert registry.append_chunk("out1", 1, b"abcd").unwrap() == 0
        assert registry.append_chunk("out1", 1, b"ef").unwrap() == 1
        record = registry.finalize_stream("out1", 1, now=200.0).unwrap()

        assert record.total_chunks == 2
        assert record.total_size == 6
        assert record.declared_hash is not None
        assert len(received) == 1
        assert received[0].payload == {
            "data_id": "out1", "version": 1, "total_chunks": 2,
            "format": "raw", "kind": "fs", "total_size": 6,
        }
        assert registry.read_whole("out1", 1).unwrap() == b"abcdef"

    def test_finalize_stream_also_emits_upload_completed_event(self, registry, event_bus):
        received = []
        event_bus.subscribe(DATA_UPLOAD_COMPLETED_EVENT, received.append)

        registry.open_stream("out1", 1, format="raw", kind="fs", chunk_bytes=4)
        registry.append_chunk("out1", 1, b"abcd")
        registry.finalize_stream("out1", 1, now=200.0)

        assert received == [
            Event(event_type=DATA_UPLOAD_COMPLETED_EVENT, payload={"data_id": "out1", "version": 1}, timestamp=200.0)
        ]

    def test_append_chunk_without_open_stream_errors(self, registry):
        result = registry.append_chunk("out1", 1, b"x")
        assert result.is_err
        assert isinstance(result.unwrap_err(), StreamNotOpenError)

    def test_finalize_without_open_stream_errors(self, registry):
        result = registry.finalize_stream("out1", 1, now=100.0)
        assert result.is_err
        assert isinstance(result.unwrap_err(), StreamAlreadyFinalizedError)

    def test_finalize_twice_errors_second_time(self, registry):
        registry.open_stream("out1", 1, format="raw", kind="fs", chunk_bytes=4)
        registry.append_chunk("out1", 1, b"abcd")
        registry.finalize_stream("out1", 1, now=100.0)

        result = registry.finalize_stream("out1", 1, now=100.0)
        assert result.is_err
        assert isinstance(result.unwrap_err(), StreamAlreadyFinalizedError)

    def test_stream_write_result_matches_declared_hash_of_appended_bytes(self, registry):
        import hashlib

        registry.open_stream("out1", 1, format="raw", kind="fs", chunk_bytes=4)
        registry.append_chunk("out1", 1, b"abcd")
        registry.append_chunk("out1", 1, b"ef")
        record = registry.finalize_stream("out1", 1, now=100.0).unwrap()

        assert record.declared_hash == hashlib.sha256(b"abcdef").hexdigest()
