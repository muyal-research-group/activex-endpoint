import contextlib
import json
import socket
import threading
import time

import pytest
import zmq
from option import Err, Ok

from axo_endpoint.core.runtime.base import InvocationHandle
from axo_endpoint.core.storage import FilesystemStorageBackend, FsKey
from axo_endpoint.core.storage.backend import StorageKey
from axo_endpoint.service.container.handle import ContainerHandle, ContainerStatus
from axo_endpoint.service.runtime.container_runtime import ContainerFunctionRuntime


def _free_tcp_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeContainer:
    """A minimal ROUTER test double standing in for a real container, so
    ContainerFunctionRuntime's ZMQ pump protocol can be tested without Docker."""

    def __init__(self):
        self.port = _free_tcp_port()
        self._sock = zmq.Context.instance().socket(zmq.ROUTER)
        self._sock.setsockopt(zmq.RCVTIMEO, 2000)
        self._sock.bind(f"tcp://127.0.0.1:{self.port}")
        self.received_dispatch = None

    def recv_dispatch(self):
        frames = self._sock.recv_multipart()
        identity = frames[0]
        self.received_dispatch = frames
        return identity

    def send_result(self, identity, job_id, status, payload):
        self._sock.send_multipart([identity, b"result", job_id.encode(), status.encode(), payload])

    def send_io_request(self, identity, request_id, op, ref: dict, data=b""):
        self._sock.send_multipart([
            identity, b"io_request", request_id.encode(), op.encode(), json.dumps(ref).encode(), data,
        ])

    def recv_any(self):
        return self._sock.recv_multipart()

    def send_raw(self, frames):
        self._sock.send_multipart(frames)

    def close(self):
        self._sock.close()


class _NoOpSummoner:
    """Stands in for a real ContainerSummoner in tests that exercise
    _pump_one_job/_handle_crash/_handle_timeout directly against a
    FakeContainer rather than going through summon() -- only dismiss() is
    ever reached from these code paths, recorded here for regression
    coverage of the crash/timeout cleanup call."""

    def __init__(self):
        self.dismiss_calls = []

    def dismiss(self, handle, reason="dismissed"):
        self.dismiss_calls.append((handle, reason))


def _make_runtime(tmp_path, data_registry=None, storage_backends=None):
    completions = []

    def on_complete(handle, result):
        completions.append((handle, result))

    runtime = ContainerFunctionRuntime(
        function_registry=None,
        summoner=_NoOpSummoner(),
        on_complete=on_complete,
        config=None,
        storage_backends=storage_backends or {"fs": FilesystemStorageBackend(root=str(tmp_path))},
        data_registry=data_registry,
    )
    return runtime, completions


def _dealer(port):
    sock = zmq.Context.instance().socket(zmq.DEALER)
    sock.setsockopt(zmq.RCVTIMEO, 3000)
    sock.connect(f"tcp://127.0.0.1:{port}")
    return sock


def _handle(port):
    return ContainerHandle(
        function_id="fn1", version=1, service_name="fn1-svc",
        mode="docker", zmq_address=f"tcp://127.0.0.1:{port}", http_address="http://x",
    )


class _FakeRecord:
    def __init__(self):
        self.runtime_spec = None


class _FakeRegistry:
    def get(self, function_ref):
        return Ok(_FakeRecord())


class _FakeSummoner:
    """Always returns the one handle it was built with -- get_handle() acts
    as if a container for this function already exists (summon() is never
    exercised by these invoke()-focused tests)."""

    def __init__(self, handle):
        self._handle = handle

    def get_handle(self, function_id, version):
        return self._handle

    def summon(self, function_id, version, spec):
        return Ok(self._handle)


def _pool_handle(port, pool_index):
    return ContainerHandle(
        function_id="fn1", version=1, service_name=f"fn1-svc-{pool_index}",
        mode="docker", zmq_address=f"tcp://127.0.0.1:{port}", http_address="http://x",
        pool_index=pool_index,
    )


class _FakePoolSummoner:
    """Mimics ContainerSummoner.summon()'s selection algorithm (reuse an
    available member, else hand back the least-busy one -- this fake never
    "grows" since it's handed a fixed, already-spawned pool) over real
    FakeContainer sockets, so ContainerFunctionRuntime's dispatch can be
    tested against several containers without Docker."""

    def __init__(self, handles):
        self._pool = list(handles)

    def get_handle(self, function_id, version):
        for h in self._pool:
            if h.status not in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED):
                return h
        return None

    def summon(self, function_id, version, spec):
        available = next(
            (h for h in self._pool if h.status not in (
                ContainerStatus.BUSY, ContainerStatus.CRASHED, ContainerStatus.DISMISSED,
            )),
            None,
        )
        if available is not None:
            return Ok(available)
        return Ok(min(self._pool, key=lambda h: h.invocation_count))


class _FakeConfig:
    def __init__(self, readiness_timeout, scratch_root):
        self.AXO_ENDPOINT_CONTAINER_READINESS_TIMEOUT_SECONDS = readiness_timeout
        self.AXO_ENDPOINT_SCRATCH_ROOT = scratch_root


def _make_runtime_for_invoke(tmp_path, handle, readiness_timeout=2.0):
    completions = []

    def on_complete(inv_handle, result):
        completions.append((inv_handle, result))

    runtime = ContainerFunctionRuntime(
        function_registry=_FakeRegistry(),
        summoner=_FakeSummoner(handle),
        on_complete=on_complete,
        config=_FakeConfig(readiness_timeout, str(tmp_path / "scratch")),
        storage_backends={"fs": FilesystemStorageBackend(root=str(tmp_path / "dataio"))},
    )
    return runtime, completions


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_invoke_returns_immediately_when_container_not_yet_ready(tmp_path):
    container = FakeContainer()
    handle = _handle(container.port)  # defaults: STARTING, ready_event unset
    runtime, completions = _make_runtime_for_invoke(tmp_path, handle, readiness_timeout=5.0)

    t0 = time.monotonic()
    result = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {"a": 1})
    elapsed = time.monotonic() - t0

    assert result.is_ok
    assert elapsed < 1.0  # returned well before the 5s readiness timeout

    # Not ready yet -- no dispatch should have been sent.
    container._sock.setsockopt(zmq.RCVTIMEO, 300)
    with pytest.raises(zmq.Again):
        container.recv_dispatch()

    # Simulate _poll_readiness succeeding -- the background waiter this
    # spawned should then dispatch the already-enqueued job.
    with handle._lock:
        handle.status = ContainerStatus.READY
    handle.ready_event.set()

    container._sock.setsockopt(zmq.RCVTIMEO, 3000)
    identity = container.recv_dispatch()
    container.send_result(identity, "job1", "ok", json.dumps(1).encode())

    assert _wait_until(lambda: len(completions) == 1)
    assert completions[0][1] == Ok(1)
    container.close()


def test_invoke_dispatches_immediately_when_already_ready(tmp_path):
    container = FakeContainer()
    handle = _handle(container.port)
    handle.status = ContainerStatus.READY
    handle.ready_event.set()
    runtime, completions = _make_runtime_for_invoke(tmp_path, handle)

    result = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {"a": 1})
    assert result.is_ok

    container._sock.setsockopt(zmq.RCVTIMEO, 2000)
    identity = container.recv_dispatch()
    container.send_result(identity, "job1", "ok", json.dumps(2).encode())

    assert _wait_until(lambda: len(completions) == 1)
    assert completions[0][1] == Ok(2)
    container.close()


def test_invoke_after_first_job_completes_still_dispatches(tmp_path):
    # Regression test: _pump() flips status to BUSY/IDLE after the first job
    # and never back to READY -- the old `status != READY` check in invoke()
    # would wrongly reject every invocation after the first for an
    # already-warm container.
    container = FakeContainer()
    handle = _handle(container.port)
    handle.status = ContainerStatus.READY
    handle.ready_event.set()
    runtime, completions = _make_runtime_for_invoke(tmp_path, handle)

    result1 = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {})
    assert result1.is_ok
    container._sock.setsockopt(zmq.RCVTIMEO, 2000)
    identity = container.recv_dispatch()
    container.send_result(identity, "job1", "ok", json.dumps(1).encode())
    assert _wait_until(lambda: len(completions) == 1)

    # Let the pump's queue-get timeout (1s) flip status back to IDLE --
    # exactly the state the old check would have wrongly rejected.
    assert _wait_until(lambda: handle.status == ContainerStatus.IDLE, timeout=3.0)

    result2 = runtime.invoke(StorageKey(id="fn1", version=1), "job2", {})
    assert result2.is_ok
    identity2 = container.recv_dispatch()
    container.send_result(identity2, "job2", "ok", json.dumps(2).encode())

    assert _wait_until(lambda: len(completions) == 2)
    assert completions[1][1] == Ok(2)
    container.close()


def test_invoke_dispatches_concurrent_jobs_to_distinct_pool_members(tmp_path):
    """Regression test for max_concurrency: 3 already-ready pool members --
    3 back-to-back invoke() calls for the same function must land on 3
    distinct containers, not queue serially behind one (also exercises the
    _pump_threads keying fix: each pool member needs its own pump thread,
    not one shared by function_id)."""
    containers = [FakeContainer() for _ in range(3)]
    handles = [_pool_handle(c.port, i) for i, c in enumerate(containers)]
    for h in handles:
        h.status = ContainerStatus.READY
        h.ready_event.set()

    completions = []

    def on_complete(inv_handle, result):
        completions.append((inv_handle, result))

    runtime = ContainerFunctionRuntime(
        function_registry=_FakeRegistry(),
        summoner=_FakePoolSummoner(handles),
        on_complete=on_complete,
        config=_FakeConfig(2.0, str(tmp_path / "scratch")),
        storage_backends={"fs": FilesystemStorageBackend(root=str(tmp_path / "dataio"))},
    )

    for i in range(3):
        result = runtime.invoke(StorageKey(id="fn1", version=1), f"job{i}", {})
        assert result.is_ok

    # Every container should have received exactly one dispatch -- proving
    # the 3 jobs landed on 3 distinct pool members.
    for i, container in enumerate(containers):
        identity = container.recv_dispatch()
        container.send_result(identity, f"job{i}", "ok", json.dumps(i).encode())

    assert _wait_until(lambda: len(completions) == 3)
    assert {outcome.unwrap() for _handle, outcome in completions} == {0, 1, 2}
    for container in containers:
        container.close()


def test_invoke_reports_failure_via_on_complete_when_never_ready(tmp_path):
    container = FakeContainer()
    handle = _handle(container.port)  # STARTING, ready_event never gets set
    runtime, completions = _make_runtime_for_invoke(tmp_path, handle, readiness_timeout=0.3)

    result = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {})
    assert result.is_ok  # invoke() itself never fails synchronously anymore

    assert _wait_until(lambda: len(completions) == 1, timeout=2.0)
    assert completions[0][1].is_err
    container.close()


def test_happy_path_dispatch_result(tmp_path):
    container = FakeContainer()
    runtime, completions = _make_runtime(tmp_path)
    sock = _dealer(container.port)
    handle = _handle(container.port)
    inv_handle = InvocationHandle(job_id="job1", function_id="fn1")

    def container_side():
        identity = container.recv_dispatch()
        container.send_result(identity, "job1", "ok", json.dumps(42).encode())

    t = threading.Thread(target=container_side, daemon=True)
    t.start()

    ok = runtime._pump_one_job(sock, handle, inv_handle, "job1", "/tmp/scratch1", {"a": 1})
    t.join(timeout=2.0)

    assert ok is True
    assert len(completions) == 1
    assert completions[0][1] == Ok(42)
    sock.close()
    container.close()


def test_io_request_is_resolved_against_real_blob_backend(tmp_path):
    container = FakeContainer()
    runtime, completions = _make_runtime(tmp_path)
    runtime._storage_backends["fs"].put(FsKey(path="in.bin"), b"container-fetched-me")

    sock = _dealer(container.port)
    handle = _handle(container.port)
    inv_handle = InvocationHandle(job_id="job1", function_id="fn1")

    def container_side():
        identity = container.recv_dispatch()
        container.send_io_request(identity, "req1", "read", {"kind": "fs", "location": "in.bin", "format": "raw"})
        frames = container.recv_any()
        assert frames[1] == b"io_reply"
        assert frames[2] == b"req1"
        assert frames[3] == b"ok"
        assert frames[4] == b"container-fetched-me"
        container.send_result(identity, "job1", "ok", json.dumps("done").encode())

    t = threading.Thread(target=container_side, daemon=True)
    t.start()

    ok = runtime._pump_one_job(sock, handle, inv_handle, "job1", "/tmp/scratch1", {})
    t.join(timeout=2.0)

    assert ok is True
    assert completions[0][1] == Ok("done")
    sock.close()
    container.close()


def test_chunk_stream_ops_resolve_against_data_registry(tmp_path):
    from axo_endpoint.core.data import DataRegistry
    from axo_endpoint.core.events import InMemoryEventBus
    from axo_endpoint.core.storage import InMemoryStorageBackend

    storage_backends = {"fs": FilesystemStorageBackend(root=str(tmp_path))}
    data_registry = DataRegistry(
        catalog=InMemoryStorageBackend(), blob_backends=storage_backends, event_bus=InMemoryEventBus(),
    )
    container = FakeContainer()
    runtime, completions = _make_runtime(tmp_path, data_registry=data_registry, storage_backends=storage_backends)

    sock = _dealer(container.port)
    handle = _handle(container.port)
    inv_handle = InvocationHandle(job_id="job1", function_id="fn1")

    def container_side():
        identity = container.recv_dispatch()
        ref = {"kind": "fs", "location": "out1/1", "format": "raw", "chunk_index": None}

        container.send_io_request(identity, "r1", "open_stream", ref, json.dumps({"chunk_bytes": 4}).encode())
        frames = container.recv_any()
        assert frames[3] == b"ok"

        container.send_io_request(identity, "r2", "append_chunk", ref, b"abcd")
        frames = container.recv_any()
        assert frames[3] == b"ok"

        container.send_io_request(identity, "r3", "append_chunk", ref, b"ef")
        frames = container.recv_any()
        assert frames[3] == b"ok"

        container.send_io_request(identity, "r4", "finalize_stream", ref, b"")
        frames = container.recv_any()
        assert frames[3] == b"ok"

        chunk0_ref = {**ref, "chunk_index": 0}
        container.send_io_request(identity, "r5", "read_chunk", chunk0_ref)
        frames = container.recv_any()
        assert frames[3] == b"ok"
        assert frames[4] == b"abcd"

        container.send_result(identity, "job1", "ok", json.dumps("done").encode())

    t = threading.Thread(target=container_side, daemon=True)
    t.start()

    ok = runtime._pump_one_job(sock, handle, inv_handle, "job1", "/tmp/scratch1", {})
    t.join(timeout=2.0)

    assert ok is True
    assert completions[0][1] == Ok("done")
    assert data_registry.read_whole("out1", 1).unwrap() == b"abcdef"
    sock.close()
    container.close()


def test_crash_mid_exchange_fails_job(tmp_path):
    """The container dying mid-exchange is only ever actually detected via
    heartbeating now (a bare recv timeout on its own is treated as "maybe
    just slow," not a crash) -- so this test wires up the same
    _open_pump_socket() production uses, rather than a bare DEALER, to
    exercise the real mechanism instead of the pre-fix "any timeout = crash"
    shortcut."""
    container = FakeContainer()
    runtime, completions = _make_runtime(tmp_path)
    handle = _handle(container.port)
    sock, disconnected = runtime._open_pump_socket(handle)
    inv_handle = InvocationHandle(job_id="job1", function_id="fn1")

    def container_side():
        container.recv_dispatch()
        container.close()  # simulate the container dying without replying

    t = threading.Thread(target=container_side, daemon=True)
    t.start()

    ok = runtime._pump_one_job(sock, handle, inv_handle, "job1", "/tmp/scratch1", {}, disconnected)
    t.join(timeout=2.0)

    assert ok is False
    assert len(completions) == 1
    assert completions[0][1].is_err
    assert "disconnected" in str(completions[0][1].unwrap_err())
    assert runtime._summoner.dismiss_calls == [(handle, "crashed")]
    sock.close()


def test_slow_but_alive_container_is_not_falsely_treated_as_crashed(tmp_path):
    """Regression test for the core bug this fix addresses: a job that
    legitimately takes a while (crossing at least one recv-poll cycle) must
    still succeed -- a quiet socket on its own is no longer evidence of a
    crash, only a real disconnect or an exceeded max_duration_seconds is."""
    container = FakeContainer()
    runtime, completions = _make_runtime(tmp_path)
    handle = _handle(container.port)  # max_duration_seconds defaults to 0 (unlimited)
    sock, disconnected = runtime._open_pump_socket(handle)
    inv_handle = InvocationHandle(job_id="job1", function_id="fn1")

    def container_side():
        identity = container.recv_dispatch()
        time.sleep(1.5)  # longer than one recv-poll cycle (1s)
        container.send_result(identity, "job1", "ok", json.dumps("slow-but-fine").encode())

    t = threading.Thread(target=container_side, daemon=True)
    t.start()

    ok = runtime._pump_one_job(sock, handle, inv_handle, "job1", "/tmp/scratch1", {}, disconnected)
    t.join(timeout=3.0)

    assert ok is True
    assert completions[0][1] == Ok("slow-but-fine")
    sock.close()
    container.close()


def test_job_exceeding_max_duration_seconds_times_out_not_crashes(tmp_path):
    container = FakeContainer()
    runtime, completions = _make_runtime(tmp_path)
    handle = _handle(container.port)
    handle.max_duration_seconds = 0.5
    sock, disconnected = runtime._open_pump_socket(handle)
    inv_handle = InvocationHandle(job_id="job1", function_id="fn1")

    def container_side():
        container.recv_dispatch()  # receives the dispatch but never replies

    t = threading.Thread(target=container_side, daemon=True)
    t.start()

    ok = runtime._pump_one_job(sock, handle, inv_handle, "job1", "/tmp/scratch1", {}, disconnected)
    t.join(timeout=2.0)

    assert ok is False
    assert len(completions) == 1
    err = completions[0][1].unwrap_err()
    assert err.name == "JOB_TIMEOUT"
    assert handle.status == ContainerStatus.CRASHED  # recycled, same consequence as a real crash
    assert runtime._summoner.dismiss_calls == [(handle, "timeout")]
    sock.close()
    container.close()


def test_malformed_io_request_frame_count_fails_cleanly_not_unhandled(tmp_path):
    container = FakeContainer()
    runtime, completions = _make_runtime(tmp_path)
    sock = _dealer(container.port)
    handle = _handle(container.port)
    inv_handle = InvocationHandle(job_id="job1", function_id="fn1")

    def container_side():
        identity = container.recv_dispatch()
        # io_request with only 3 frames instead of the expected 5
        container.send_raw([identity, b"io_request", b"req1"])

    t = threading.Thread(target=container_side, daemon=True)
    t.start()

    ok = runtime._pump_one_job(sock, handle, inv_handle, "job1", "/tmp/scratch1", {})
    t.join(timeout=2.0)

    assert ok is False
    assert len(completions) == 1
    assert completions[0][1].is_err
    sock.close()
    container.close()
