import threading
import time

import cloudpickle
import pytest

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.storage import InMemoryStorageBackend
from axo_endpoint.service.runtime.process_runtime import ProcessFunctionRuntime


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


@pytest.fixture
def registry():
    backend = InMemoryStorageBackend()
    return FunctionRegistry(backend=backend, event_bus=InMemoryEventBus())


def _register(registry, name, func, now=0.0):
    return registry.register(name=name, version=1, code=cloudpickle.dumps(func), now=now).unwrap()


def _make_runtime(registry, scratch_root, **kwargs):
    completions = []
    lock = threading.Lock()

    def on_complete(handle, result):
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


def test_sweep_idle_kills_the_worker_process(registry, tmp_path):
    key = _register(registry, "pid_sweep", _get_pid)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {})
    assert _wait_until(lambda: len(completions) == 1)
    pid_before = completions[0][1].unwrap()
    process_before = runtime._workers.get_or_none("pid_sweep").process

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
    process_before = runtime._workers.get_or_none("pid_cap").process

    evicted = runtime.sweep_max_invocations(max_invocations=1)
    assert evicted == ["pid_cap"]
    assert _wait_until(lambda: not process_before.is_alive())
