import pytest

from axo_endpoint.core.consensus.membership import ClusterMember
from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend
from axo_endpoint.service.blob_replication import BlobReplicator


@pytest.fixture
def registry(tmp_path):
    return DataRegistry(
        catalog=InMemoryStorageBackend(),
        blob_backends={"fs": FilesystemStorageBackend(root=str(tmp_path))},
        event_bus=InMemoryEventBus(),
    )


@pytest.fixture
def replicator(registry):
    return BlobReplicator(
        data_registry=registry,
        storage_backends=registry._blob_backends,
        chunk_bytes=4,
        rate_limit_bytes_per_second=1_000_000,
        enabled_kinds=["fs"],
    )


def _register_and_fill(registry, name="df1", data=b"hello-world", chunk_bytes=4):
    record = registry.register(
        name=name, version=1, format="raw", kind="fs", total_size=len(data), chunk_bytes=chunk_bytes, now=100.0,
    ).unwrap()
    for i in range(record.total_chunks):
        start = i * chunk_bytes
        registry.store_chunk(name, 1, i, data[start:start + chunk_bytes])
    return record


def _member(peer_id="node-b", rpc_uri="tcp://127.0.0.1:9999"):
    return ClusterMember(peer_id=peer_id, rpc_uri=rpc_uri)


class _FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _FakeLogger:
    def __init__(self):
        self.info_events = []

    def info_event(self, event, **kwargs):
        self.info_events.append((event, kwargs))

    def debug_event(self, event, **kwargs):
        pass

    def warning_event(self, event, **kwargs):
        pass

    def error_event(self, event, **kwargs):
        pass


def test_run_tick_pushes_missing_chunks_when_complete_on_leader(registry, replicator):
    _register_and_fill(registry)

    def query_status_fn(rpc_uri, name, version):
        return {"present_chunk_indices": [], "complete": False}

    pushed = []

    def push_chunk_fn(rpc_uri, name, version, chunk_index, chunk):
        pushed.append((rpc_uri, name, version, chunk_index, chunk))

    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=query_status_fn,
        push_chunk_fn=push_chunk_fn, elapsed_seconds=1.0,
    )

    ordered = b"".join(c[4] for c in sorted(pushed, key=lambda c: c[3]))
    assert ordered == b"hello-world"


def test_run_tick_skips_chunks_the_peer_already_has(registry, replicator):
    _register_and_fill(registry)

    def query_status_fn(rpc_uri, name, version):
        return {"present_chunk_indices": [0, 1], "complete": False}

    pushed = []
    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=query_status_fn,
        push_chunk_fn=lambda *a: pushed.append(a), elapsed_seconds=1.0,
    )

    pushed_indices = sorted(p[3] for p in pushed)
    assert 0 not in pushed_indices
    assert 1 not in pushed_indices


def test_run_tick_skips_peer_already_reporting_complete(registry, replicator):
    _register_and_fill(registry)

    def query_status_fn(rpc_uri, name, version):
        return {"present_chunk_indices": [0, 1, 2], "complete": True}

    pushed = []
    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=query_status_fn,
        push_chunk_fn=lambda *a: pushed.append(a), elapsed_seconds=1.0,
    )
    assert pushed == []


def test_run_tick_is_noop_when_not_leader(registry, replicator):
    _register_and_fill(registry)
    calls = []
    replicator.run_tick(
        is_leader=False, members=[_member()], query_status_fn=lambda *a: None,
        push_chunk_fn=lambda *a: calls.append(a), elapsed_seconds=1.0,
    )
    assert calls == []


def test_run_tick_is_noop_when_no_members(registry, replicator):
    _register_and_fill(registry)
    calls = []
    replicator.run_tick(
        is_leader=True, members=[], query_status_fn=lambda *a: None,
        push_chunk_fn=lambda *a: calls.append(a), elapsed_seconds=1.0,
    )
    assert calls == []


def test_leader_completeness_gate_skips_incomplete_records(registry, replicator):
    # 9/10 chunks (well, 2/3 given chunk_bytes=4) on the leader -- never
    # pushed to any peer at all, not even the chunks it does have.
    record = registry.register(
        name="df1", version=1, format="raw", kind="fs", total_size=11, chunk_bytes=4, now=100.0,
    ).unwrap()
    registry.store_chunk("df1", 1, 0, b"hell")
    registry.store_chunk("df1", 1, 1, b"o-wo")
    # chunk 2 ("rld") deliberately never stored -- leader itself is incomplete

    status_calls = []

    def query_status_fn(rpc_uri, name, version):
        status_calls.append((name, version))
        return {"present_chunk_indices": [], "complete": False}

    pushed = []
    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=query_status_fn,
        push_chunk_fn=lambda *a: pushed.append(a), elapsed_seconds=1.0,
    )

    assert status_calls == []  # never even queried a peer about it
    assert pushed == []


def test_kind_filter_skips_disabled_kinds(registry):
    replicator = BlobReplicator(
        data_registry=registry,
        storage_backends=registry._blob_backends,
        chunk_bytes=4,
        rate_limit_bytes_per_second=1_000_000,
        enabled_kinds=["s3"],  # "fs" is not enabled
    )
    _register_and_fill(registry)

    pushed = []
    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=lambda *a: {"present_chunk_indices": [], "complete": False},
        push_chunk_fn=lambda *a: pushed.append(a), elapsed_seconds=1.0,
    )
    assert pushed == []


def test_rate_limit_caps_bytes_pushed_in_one_tick(registry):
    replicator = BlobReplicator(
        data_registry=registry,
        storage_backends=registry._blob_backends,
        chunk_bytes=4,
        rate_limit_bytes_per_second=4,  # 1 chunk's worth per second
        enabled_kinds=["fs"],
    )
    _register_and_fill(registry, data=b"hello-world")  # 3 chunks of <=4 bytes

    pushed = []
    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=lambda *a: {"present_chunk_indices": [], "complete": False},
        push_chunk_fn=lambda *a: pushed.append(a), elapsed_seconds=1.0,
    )
    assert len(pushed) == 1  # budget = 4 bytes/sec * 1s = 4 bytes = exactly one chunk


def test_peer_status_for_reflects_last_tick(registry, replicator):
    _register_and_fill(registry)
    replicator.run_tick(
        is_leader=True, members=[_member("node-b")],
        query_status_fn=lambda *a: {"present_chunk_indices": [0], "complete": False},
        push_chunk_fn=lambda *a: None, elapsed_seconds=1.0,
    )

    status = replicator.peer_status_for("df1", 1)
    assert "node-b" in status
    assert status["node-b"].present_chunks == 1
    assert status["node-b"].complete is False


def test_peer_status_for_unknown_dataset_is_empty(replicator):
    assert replicator.peer_status_for("missing", 1) == {}


def test_run_tick_logs_once_on_transition_to_complete(registry):
    _register_and_fill(registry)
    clock = _FakeClock()
    logger = _FakeLogger()
    replicator = BlobReplicator(
        data_registry=registry, storage_backends=registry._blob_backends,
        chunk_bytes=4, rate_limit_bytes_per_second=1_000_000, enabled_kinds=["fs"],
        recheck_seconds=300.0, now_fn=clock, logger=logger,
    )

    query_status_fn = lambda *a: {"present_chunk_indices": [0, 1, 2], "complete": True}
    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=query_status_fn,
        push_chunk_fn=lambda *a: None, elapsed_seconds=1.0,
    )
    assert len(logger.info_events) == 1
    event, kwargs = logger.info_events[0]
    assert kwargs["data_name"] == "df1"
    assert kwargs["peer_id"] == "node-b"

    # Second tick, still complete -- must not log again.
    clock.advance(1.0)
    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=query_status_fn,
        push_chunk_fn=lambda *a: None, elapsed_seconds=1.0,
    )
    assert len(logger.info_events) == 1


def test_run_tick_skips_querying_peer_already_complete_within_recheck_window(registry):
    _register_and_fill(registry)
    clock = _FakeClock()
    replicator = BlobReplicator(
        data_registry=registry, storage_backends=registry._blob_backends,
        chunk_bytes=4, rate_limit_bytes_per_second=1_000_000, enabled_kinds=["fs"],
        recheck_seconds=300.0, now_fn=clock,
    )

    query_calls = []

    def query_status_fn(rpc_uri, name, version):
        query_calls.append((name, version))
        return {"present_chunk_indices": [0, 1, 2], "complete": True}

    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=query_status_fn,
        push_chunk_fn=lambda *a: None, elapsed_seconds=1.0,
    )
    assert len(query_calls) == 1

    # Well within the recheck window -- must not query again.
    clock.advance(1.0)
    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=query_status_fn,
        push_chunk_fn=lambda *a: None, elapsed_seconds=1.0,
    )
    assert len(query_calls) == 1


def test_run_tick_requeries_after_recheck_window_elapses(registry):
    _register_and_fill(registry)
    clock = _FakeClock()
    logger = _FakeLogger()
    replicator = BlobReplicator(
        data_registry=registry, storage_backends=registry._blob_backends,
        chunk_bytes=4, rate_limit_bytes_per_second=1_000_000, enabled_kinds=["fs"],
        recheck_seconds=10.0, now_fn=clock, logger=logger,
    )

    query_calls = []

    def query_status_fn(rpc_uri, name, version):
        query_calls.append((name, version))
        return {"present_chunk_indices": [0, 1, 2], "complete": True}

    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=query_status_fn,
        push_chunk_fn=lambda *a: None, elapsed_seconds=1.0,
    )
    assert len(query_calls) == 1

    clock.advance(20.0)  # past the 10s recheck window
    replicator.run_tick(
        is_leader=True, members=[_member()], query_status_fn=query_status_fn,
        push_chunk_fn=lambda *a: None, elapsed_seconds=1.0,
    )
    assert len(query_calls) == 2
    # Still complete both times -- the "transition" log fires only once.
    assert len(logger.info_events) == 1
