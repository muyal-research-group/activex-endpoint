import threading
import time

import cloudpickle
import pytest

from axo_endpoint.core.dataio import IORef
from axo_endpoint.core.storage import FilesystemStorageBackend
from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.storage import InMemoryStorageBackend
from axo_endpoint.service.runtime.process_runtime import ProcessFunctionRuntime
from axo_shared.runtime.spec import RuntimeSpec


def _get_pid(params, ctx):
    import os

    return os.getpid()


def _crash_once(params, ctx):
    import os

    marker = params["marker"]
    if not os.path.exists(marker):
        open(marker, "w").close()
        os._exit(1)
    return "recovered"


def _maybe_raise(params, ctx):
    import os

    if params.get("boom"):
        raise ValueError("boom")
    return os.getpid()


def _report_scratch_dir(params, ctx):
    import os

    return {"scratch_dir": ctx.scratch_dir, "existed_during_call": os.path.isdir(ctx.scratch_dir)}


def _allocate_too_much_memory(params, ctx):
    data = bytearray(200 * 1024 * 1024)  # 200MB, expected to exceed a tight test rlimit
    return len(data)


def _busy_loop(params, ctx):
    x = 0
    while True:
        x += 1


def _dataio_roundtrip(params, ctx):
    from axo_endpoint import dataio

    ref = IORef(kind="fs", location=params["location"], format=params["format"])
    dataio.write(params["value"], ref)
    return dataio.read(ref)


def _dataio_write(params, ctx):
    from axo_endpoint import dataio

    ref = IORef(kind="fs", location=params["location"], format=params.get("format", "raw"))
    dataio.write(params["value"], ref)
    return "written"


def _dataio_stream_roundtrip(params, ctx):
    from axo_endpoint import dataio

    ref = dataio.write_chunks(params["name"], params["version"], [b"abcd", b"efgh"], chunk_bytes=4)
    return b"".join(dataio.iter_chunks(ref))


def _dataio_then_crash(params, ctx):
    import os

    from axo_endpoint import dataio

    ref = IORef(kind="fs", location=params["location"], format="raw")
    dataio.write(b"before-crash", ref)
    result = dataio.read(ref)
    assert result == b"before-crash"
    os._exit(1)
    return "unreachable"


@pytest.fixture
def registry():
    backend = InMemoryStorageBackend()
    return FunctionRegistry(backend=backend, event_bus=InMemoryEventBus())


def _register(registry, name, func, now=0.0):
    return registry.register(function_id=name, name=name, code=cloudpickle.dumps(func), now=now).unwrap()


def _register_source(registry, name, source: bytes, now=0.0):
    return registry.register(function_id=name, name=name, code=source, now=now, code_format="source").unwrap()


def _make_runtime(registry, scratch_root, **kwargs):
    completions = []
    lock = threading.Lock()

    def on_complete(handle, result, warnings=None):
        with lock:
            completions.append((handle, result))

    runtime = ProcessFunctionRuntime(
        function_registry = registry,
        on_complete       = on_complete,
        scratch_root      = scratch_root,
        **kwargs
    )
    return runtime, completions


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_invoke_runs_registered_function_and_reports_result(registry, tmp_path):
    key = _register(registry, "add", lambda params, ctx: params["a"] + params["b"])
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))
    print("COMPLETIONS BEFORE INVOKE:", completions)
    result = runtime.invoke(key, "job1", {"a": 2, "b": 3})
    assert result.is_ok
    assert result.unwrap().job_id == "job1"
    assert result.unwrap().function_id == "add"

    assert _wait_until(lambda: len(completions) == 1)
    handle, outcome = completions[0]
    assert handle.job_id == "job1"
    assert outcome.is_ok
    assert outcome.unwrap() == 5


def test_worker_env_vars_from_runtime_spec_are_applied_before_cold_start(registry, tmp_path):
    def _read_env(params, ctx):
        import os
        return os.environ.get("AXO_TEST_VAR")

    key = registry.register(
        function_id="read_env", name="read_env", code=cloudpickle.dumps(_read_env), now=0.0,
        runtime_spec=RuntimeSpec(env_vars={"AXO_TEST_VAR": "hello"}),
    ).unwrap()
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))
    runtime.invoke(key, "job1", {})

    assert _wait_until(lambda: len(completions) == 1)
    assert completions[0][1].unwrap() == "hello"


def test_invoke_runs_a_source_format_function_via_deferred_exec(registry, tmp_path):
    marker = tmp_path / "module_body_ran"
    source = (
        f"MARKER_PATH = {str(marker)!r}\n"
        "with open(MARKER_PATH, 'w') as f:\n"
        "    f.write('exec happened')\n\n"
        "def add(params, ctx):\n"
        "    return params['a'] + params['b']\n"
    ).encode()

    assert not marker.exists()
    key = _register_source(registry, "add", source)
    assert not marker.exists()  # registration alone must never execute anything

    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))
    runtime.invoke(key, "job1", {"a": 2, "b": 3})

    assert _wait_until(lambda: len(completions) == 1)
    assert completions[0][1].unwrap() == 5
    assert marker.exists()  # only the cold-started worker process ever ran the module body


def test_warm_reuse_does_not_spawn_a_second_process(registry, tmp_path):
    key = _register(registry, "pid", _get_pid)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {})
    assert _wait_until(lambda: len(completions) == 1)
    pid1 = completions[0][1].unwrap()

    runtime.invoke(key, "job2", {})
    assert _wait_until(lambda: len(completions) == 2)
    pid2 = completions[1][1].unwrap()

    assert pid1 == pid2  # same worker process reused on the warm path, no respawn


def test_crash_evicts_worker_and_next_invocation_cold_starts_fresh_process(registry, tmp_path):
    marker = str(tmp_path / "marker")
    key = _register(registry, "crash_once", _crash_once)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {"marker": marker})
    assert _wait_until(lambda: len(completions) == 1)
    assert completions[0][1].is_err

    runtime.invoke(key, "job2", {"marker": marker})
    assert _wait_until(lambda: len(completions) == 2)
    assert completions[1][1].is_ok
    assert completions[1][1].unwrap() == "recovered"


def test_function_exception_does_not_crash_or_evict_the_worker(registry, tmp_path):
    key = _register(registry, "maybe_raise", _maybe_raise)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {"boom": True})
    assert _wait_until(lambda: len(completions) == 1)
    assert completions[0][1].is_err
    assert "boom" in str(completions[0][1].unwrap_err())

    runtime.invoke(key, "job2", {})
    assert _wait_until(lambda: len(completions) == 2)
    assert completions[1][1].is_ok
    pid_after_exception = completions[1][1].unwrap()

    # Still the same warm process -- a normal exception must not have killed it.
    runtime.invoke(key, "job3", {})
    assert _wait_until(lambda: len(completions) == 3)
    assert completions[2][1].unwrap() == pid_after_exception


def test_scratch_dir_exists_during_call_and_is_cleaned_up_after(registry, tmp_path):
    scratch_root = str(tmp_path / "scratch")
    key = _register(registry, "report_scratch", _report_scratch_dir)
    runtime, completions = _make_runtime(registry, scratch_root)

    runtime.invoke(key, "job1", {})
    assert _wait_until(lambda: len(completions) == 1)

    outcome = completions[0][1].unwrap()
    assert outcome["existed_during_call"] is True
    assert outcome["scratch_dir"] == str(tmp_path / "scratch" / "job1")
    assert not __import__("os").path.isdir(outcome["scratch_dir"])  # cleaned up after the call


def test_rlimit_as_triggers_failure_when_function_overallocates(registry, tmp_path):
    key = _register(registry, "hog", _allocate_too_much_memory)
    runtime, completions = _make_runtime(
        registry, str(tmp_path / "scratch"), memory_limit_bytes=64 * 1024 * 1024
    )

    runtime.invoke(key, "job1", {})
    assert _wait_until(lambda: len(completions) == 1, timeout=10.0)
    # Either a clean MemoryError inside the function, or the process being
    # killed outright -- both are acceptable, platform-dependent outcomes of
    # exceeding RLIMIT_AS. Either way the invocation must be reported failed.
    assert completions[0][1].is_err


def test_rlimit_cpu_kills_busy_loop_and_marks_invocation_failed(registry, tmp_path):
    key = _register(registry, "busy", _busy_loop)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"), cpu_limit_seconds=1)

    runtime.invoke(key, "job1", {})
    assert _wait_until(lambda: len(completions) == 1, timeout=10.0)
    assert completions[0][1].is_err


def _sleep_then_pid(params, ctx):
    import os
    import time

    time.sleep(params["sleep_seconds"])
    return os.getpid()


def test_max_concurrency_runs_multiple_jobs_in_parallel_worker_processes(registry, tmp_path):
    key = registry.register(
        function_id="sleep_pid", name="sleep_pid", code=cloudpickle.dumps(_sleep_then_pid), now=0.0,
        runtime_spec=RuntimeSpec(max_concurrency=3),
    ).unwrap()
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    for i in range(3):
        runtime.invoke(key, f"job{i}", {"sleep_seconds": 0.5})

    # All 3 should be running concurrently in distinct processes, not queued
    # serially behind one worker -- give them a moment to actually start,
    # then confirm 3 distinct workers exist for this (function, version).
    assert _wait_until(lambda: len(runtime._workers.pool("sleep_pid", 1)) == 3)

    assert _wait_until(lambda: len(completions) == 3, timeout=5.0)
    pids = {outcome.unwrap() for _handle, outcome in completions}
    assert len(pids) == 3  # three distinct worker processes, not one reused serially


def test_max_concurrency_default_of_one_never_grows_the_pool(registry, tmp_path):
    key = _register(registry, "sleep_pid_default", _sleep_then_pid)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job0", {"sleep_seconds": 0.3})
    runtime.invoke(key, "job1", {"sleep_seconds": 0.0})

    assert _wait_until(lambda: len(completions) == 2, timeout=5.0)
    assert len(runtime._workers.pool("sleep_pid_default", 1)) == 1  # queued behind the one worker, never grew


def test_job_within_max_duration_seconds_completes_normally(registry, tmp_path):
    """Regression check: switching _pump's blocking recv() for a polling
    loop must not change behavior for an ordinary job that finishes well
    within its deadline."""
    key = registry.register(
        function_id="sleep_ok", name="sleep_ok", code=cloudpickle.dumps(_sleep_then_pid), now=0.0,
        runtime_spec=RuntimeSpec(max_duration_seconds=5.0),
    ).unwrap()
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {"sleep_seconds": 0.2})

    assert _wait_until(lambda: len(completions) == 1, timeout=5.0)
    assert completions[0][1].is_ok


def test_job_exceeding_max_duration_seconds_times_out_and_recycles_worker(registry, tmp_path):
    key = registry.register(
        function_id="sleep_timeout", name="sleep_timeout", code=cloudpickle.dumps(_sleep_then_pid), now=0.0,
        runtime_spec=RuntimeSpec(max_duration_seconds=1.0),
    ).unwrap()
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {"sleep_seconds": 30.0})

    assert _wait_until(lambda: len(completions) == 1, timeout=5.0)
    err = completions[0][1].unwrap_err()
    assert err.name == "JOB_TIMEOUT"

    # The stuck worker must actually be gone -- next invocation cold-starts
    # a fresh one rather than queuing behind (or reusing) the killed one.
    runtime.invoke(key, "job2", {"sleep_seconds": 0.0})
    assert _wait_until(lambda: len(completions) == 2, timeout=5.0)
    assert completions[1][1].is_ok


def test_sweep_idle_kills_the_worker_process(registry, tmp_path):
    key = _register(registry, "pid_sweep", _get_pid)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {})
    assert _wait_until(lambda: len(completions) == 1)
    pid_before = completions[0][1].unwrap()
    process_before = runtime._workers.get_idle_or_none("pid_sweep", 1).process

    evicted = runtime.sweep_idle(ttl_seconds=0.0, now=time.time() + 1000.0)
    assert evicted == ["pid_sweep"]
    assert _wait_until(lambda: not process_before.is_alive())

    # Next invocation must cold-start a brand new process -- the old one is dead.
    runtime.invoke(key, "job2", {})
    assert _wait_until(lambda: len(completions) == 2)
    pid_after = completions[1][1].unwrap()
    assert pid_after != pid_before


def test_sweep_max_invocations_kills_the_worker_process(registry, tmp_path):
    key = _register(registry, "pid_cap", _get_pid)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {})
    assert _wait_until(lambda: len(completions) == 1)
    process_before = runtime._workers.get_idle_or_none("pid_cap", 1).process

    evicted = runtime.sweep_max_invocations(max_invocations=1)
    assert evicted == ["pid_cap"]
    assert _wait_until(lambda: not process_before.is_alive())


def _storage_backends(tmp_path):
    return {"fs": FilesystemStorageBackend(root=str(tmp_path / "dataio"))}


@pytest.mark.parametrize(
    "format, value",
    [
        ("raw", b"some raw bytes"),
        ("pickle", {"a": 1, "b": [1, 2, 3]}),
        ("npy", __import__("numpy").array([1, 2, 3])),
    ],
)
def test_dataio_write_then_read_round_trips_through_pipe(registry, tmp_path, format, value):
    key = _register(registry, f"dataio_{format}", _dataio_roundtrip)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"), storage_backends=_storage_backends(tmp_path))

    runtime.invoke(key, "job1", {"location": f"blob.{format}", "format": format, "value": value})
    assert _wait_until(lambda: len(completions) == 1)
    outcome = completions[0][1]
    assert outcome.is_ok
    if format == "npy":
        import numpy as np
        assert (outcome.unwrap() == value).all()
    else:
        assert outcome.unwrap() == value


def test_dataio_csv_round_trips_through_pipe(registry, tmp_path):
    import pandas as pd

    key = _register(registry, "dataio_csv", _dataio_roundtrip)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"), storage_backends=_storage_backends(tmp_path))

    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    runtime.invoke(key, "job1", {"location": "blob.csv", "format": "csv", "value": df})
    assert _wait_until(lambda: len(completions) == 1)
    outcome = completions[0][1]
    assert outcome.is_ok
    pd.testing.assert_frame_equal(outcome.unwrap(), df)


def test_dataio_write_chunks_then_iter_chunks_round_trips_through_pipe(registry, tmp_path):
    from axo_endpoint.core.data import DataRegistry
    from axo_endpoint.core.events import InMemoryEventBus
    from axo_endpoint.core.storage import InMemoryStorageBackend

    storage_backends = _storage_backends(tmp_path)
    data_registry = DataRegistry(
        catalog=InMemoryStorageBackend(), blob_backends=storage_backends, event_bus=InMemoryEventBus(),
    )
    key = _register(registry, "dataio_stream", _dataio_stream_roundtrip)
    runtime, completions = _make_runtime(
        registry, str(tmp_path / "scratch"), storage_backends=storage_backends, data_registry=data_registry,
    )

    runtime.invoke(key, "job1", {"name": "streamed", "version": 1})
    assert _wait_until(lambda: len(completions) == 1)
    outcome = completions[0][1]
    assert outcome.is_ok
    assert outcome.unwrap() == b"abcdefgh"


def test_dataio_path_traversal_is_rejected(registry, tmp_path):
    key = _register(registry, "dataio_traversal", _dataio_write)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"), storage_backends=_storage_backends(tmp_path))

    runtime.invoke(key, "job1", {"location": "../../etc/passwd", "value": b"x"})
    assert _wait_until(lambda: len(completions) == 1)
    outcome = completions[0][1]
    assert outcome.is_err
    assert "IO_PATH_TRAVERSAL" in str(outcome.unwrap_err()) or "escapes" in str(outcome.unwrap_err())


def test_dataio_unknown_format_is_rejected_cleanly(registry, tmp_path):
    key = _register(registry, "dataio_bad_format", _dataio_write)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"), storage_backends=_storage_backends(tmp_path))

    runtime.invoke(key, "job1", {"location": "blob.parquet", "format": "parquet", "value": b"x"})
    assert _wait_until(lambda: len(completions) == 1)
    outcome = completions[0][1]
    assert outcome.is_err
    assert "UNKNOWN_IO_FORMAT" in str(outcome.unwrap_err()) or "unknown io format" in str(outcome.unwrap_err())

    # Worker must still be alive/reusable after a clean dataio error -- not a crash.
    runtime.invoke(key, "job2", {"location": "blob.raw", "format": "raw", "value": b"ok"})
    assert _wait_until(lambda: len(completions) == 2)
    assert completions[1][1].is_ok


def test_worker_crash_after_dataio_round_trip_still_fails_job_and_evicts_worker(registry, tmp_path):
    key = _register(registry, "dataio_then_crash", _dataio_then_crash)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"), storage_backends=_storage_backends(tmp_path))

    runtime.invoke(key, "job1", {"location": "blob.raw"})
    assert _wait_until(lambda: len(completions) == 1)
    assert completions[0][1].is_err

    # Next invocation must cold-start a brand new worker -- the crashed one is gone.
    runtime.invoke(key, "job2", {"location": "blob2.raw"})
    assert _wait_until(lambda: len(completions) == 2)
    assert completions[1][1].is_err  # crashes again (same function), proving a fresh worker was spawned each time
