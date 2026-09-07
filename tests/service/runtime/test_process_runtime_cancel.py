import threading
import time

import cloudpickle
import pytest

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.storage import InMemoryStorageBackend
from axo_endpoint.service.runtime.process_runtime import ProcessFunctionRuntime


def _sleep_then_pid(params, ctx):
    import os
    import time

    time.sleep(params["sleep_seconds"])
    return os.getpid()


@pytest.fixture
def registry():
    return FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=InMemoryEventBus())


def _register(registry, name, func, now=0.0):
    return registry.register(function_id=name, name=name, code=cloudpickle.dumps(func), now=now).unwrap()


def _make_runtime(registry, scratch_root, **kwargs):
    completions = []
    lock = threading.Lock()

    def on_complete(handle, result, warnings=None):
        with lock:
            completions.append((handle, result))

    runtime = ProcessFunctionRuntime(
        function_registry=registry, on_complete=on_complete, scratch_root=scratch_root, **kwargs,
    )
    return runtime, completions


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_cancel_in_flight_job_kills_worker_and_reports_job_cancelled_error(registry, tmp_path):
    key = _register(registry, "sleep_cancel", _sleep_then_pid)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {"sleep_seconds": 30.0})
    assert _wait_until(lambda: runtime._workers.find_by_job_id("job1") is not None)
    process = runtime._workers.find_by_job_id("job1").process

    assert runtime.cancel("job1") is True

    assert _wait_until(lambda: len(completions) == 1)
    handle, outcome = completions[0]
    assert handle.job_id == "job1"
    assert outcome.is_err
    assert outcome.unwrap_err().name == "JOB_CANCELLED"
    assert _wait_until(lambda: not process.is_alive())

    # Regression guard: killing the process wakes the pump thread's own
    # crash detection, which must not report this same job a second time
    # (e.g. as WorkerCrashedError) now that the kill has had time to land.
    time.sleep(0.3)
    assert len(completions) == 1


def test_cancel_queued_job_drops_it_before_dispatch_without_touching_the_running_one(registry, tmp_path):
    key = _register(registry, "sleep_cancel_queued", _sleep_then_pid)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {"sleep_seconds": 0.6})
    assert _wait_until(lambda: runtime._workers.find_by_job_id("job1") is not None)
    runtime.invoke(key, "job2", {"sleep_seconds": 0.0})

    assert runtime.cancel("job2") is True

    assert _wait_until(lambda: any(h.job_id == "job2" for h, _ in completions))
    job2_outcome = next(outcome for h, outcome in completions if h.job_id == "job2")
    assert job2_outcome.is_err
    assert job2_outcome.unwrap_err().name == "JOB_CANCELLED"

    # job1 was never touched -- it runs to a normal, successful completion.
    assert _wait_until(lambda: len(completions) == 2, timeout=5.0)
    job1_outcome = next(outcome for h, outcome in completions if h.job_id == "job1")
    assert job1_outcome.is_ok
    assert len(runtime._workers.pool("sleep_cancel_queued", 1)) == 1  # worker never evicted


def test_cancel_unknown_job_id_returns_false(registry, tmp_path):
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    assert runtime.cancel("no-such-job") is False
    assert completions == []


def test_cancelling_the_same_job_twice_only_succeeds_once(registry, tmp_path):
    """process_runtime.py has no retry mechanism at all -- cancel() removing
    the job from tracking entirely (rather than leaving anything behind to
    retry) is what "a cancelled job is never retried" amounts to here."""
    key = _register(registry, "sleep_cancel_twice", _sleep_then_pid)
    runtime, completions = _make_runtime(registry, str(tmp_path / "scratch"))

    runtime.invoke(key, "job1", {"sleep_seconds": 30.0})
    assert _wait_until(lambda: runtime._workers.find_by_job_id("job1") is not None)

    assert runtime.cancel("job1") is True
    assert runtime.cancel("job1") is False

    assert _wait_until(lambda: len(completions) == 1)
    assert len(completions) == 1
