import queue
import time

from option import Ok

from axo_endpoint.core.consensus.concurrency import SlotDecision
from axo_endpoint.core.runtime.base import InvocationHandle
from axo_endpoint.service.container.handle import ContainerHandle, ContainerStatus
from axo_endpoint.service.runtime.container_runtime import ContainerFunctionRuntime
from axo_shared.runtime.spec import RuntimeSpec


class _FakeConfig:
    def __init__(self, scratch_root):
        self.AXO_ENDPOINT_SCRATCH_ROOT = scratch_root


class _FakeRecord:
    def __init__(self, spec):
        self.runtime_spec = spec


class _FakeRegistry:
    def __init__(self, spec):
        self._spec = spec

    def get(self, function_ref):
        return Ok(_FakeRecord(self._spec))


class _FakeSummoner:
    """list_handles()/dismiss() are all cancel() actually needs -- mirrors
    the subset test_container_runtime_retry.py's own fake exercises."""

    def __init__(self, handles):
        self._handles = list(handles)
        self.dismiss_calls = []

    def list_handles(self):
        return list(self._handles)

    def dismiss(self, handle, reason="dismissed"):
        self.dismiss_calls.append((handle, reason))
        handle.status = ContainerStatus.DISMISSED


class _FakeConcurrencyClient:
    def __init__(self):
        self.release_calls = []

    def request_growth(self, function_id, version, max_concurrency):
        return Ok(SlotDecision.granted(0))

    def release(self, function_id, version, slot_index):
        self.release_calls.append((function_id, version, slot_index))


def _handle(function_id="fn1", version=1, pool_index=0):
    h = ContainerHandle(
        function_id=function_id, version=version, service_name=f"{function_id}-svc-{pool_index}",
        mode="docker", zmq_address="tcp://127.0.0.1:1", http_address="http://x",
        pool_index=pool_index,
    )
    h.ready_event.set()
    h.status = ContainerStatus.IDLE
    return h


def _runtime(tmp_path, summoner, max_retries=3):
    completions = []

    def on_complete(inv_handle, result, warnings=None):
        completions.append((inv_handle, result))

    runtime = ContainerFunctionRuntime(
        function_registry=_FakeRegistry(RuntimeSpec(type="container", max_concurrency=2, max_retries=max_retries)),
        summoner=summoner,
        on_complete=on_complete,
        config=_FakeConfig(str(tmp_path)),
    )
    return runtime, completions


def test_cancel_in_flight_job_dismisses_container_and_reports_job_cancelled_error(tmp_path):
    handle = _handle()
    handle.status = ContainerStatus.BUSY
    handle.current_job_id = "job1"
    summoner = _FakeSummoner([handle])
    runtime, completions = _runtime(tmp_path, summoner)
    concurrency_client = _FakeConcurrencyClient()
    runtime.attach_cluster_placement(concurrency_client, forward_job_fn=lambda *a: Ok(None))

    assert runtime.cancel("job1") is True

    assert len(completions) == 1
    inv_handle, outcome = completions[0]
    assert inv_handle.job_id == "job1"
    assert outcome.is_err
    assert outcome.unwrap_err().name == "JOB_CANCELLED"
    assert summoner.dismiss_calls == [(handle, "cancelled")]
    assert concurrency_client.release_calls == [("fn1", 1, 0)]


def test_cancel_drains_and_fails_sibling_queued_jobs_with_container_crash_error(tmp_path):
    handle = _handle()
    handle.status = ContainerStatus.BUSY
    handle.current_job_id = "job1"
    handle._job_queue = queue.Queue()
    handle._job_queue.put(("job2", "/scratch/job2", {}))
    handle._job_queue.put(("job3", "/scratch/job3", {}))
    summoner = _FakeSummoner([handle])
    runtime, completions = _runtime(tmp_path, summoner)

    assert runtime.cancel("job1") is True

    by_job_id = {inv.job_id: outcome for inv, outcome in completions}
    assert set(by_job_id) == {"job1", "job2", "job3"}
    assert by_job_id["job1"].unwrap_err().name == "JOB_CANCELLED"
    assert by_job_id["job2"].unwrap_err().name == "CONTAINER_CRASH_ERROR"
    assert by_job_id["job3"].unwrap_err().name == "CONTAINER_CRASH_ERROR"
    assert handle._job_queue.empty()


def test_cancel_queued_job_drops_it_without_dismissing_the_container(tmp_path):
    handle = _handle()
    handle.status = ContainerStatus.BUSY
    handle.current_job_id = "job1"  # some other job is in flight
    handle._job_queue = queue.Queue()
    handle._job_queue.put(("job2", "/scratch/job2", {}))
    summoner = _FakeSummoner([handle])
    runtime, completions = _runtime(tmp_path, summoner)

    assert runtime.cancel("job2") is True

    assert len(completions) == 1
    inv_handle, outcome = completions[0]
    assert inv_handle.job_id == "job2"
    assert outcome.unwrap_err().name == "JOB_CANCELLED"
    assert "before it started" in outcome.unwrap_err().message
    assert summoner.dismiss_calls == []  # container itself never touched
    assert handle._job_queue.empty()
    assert handle.current_job_id == "job1"  # untouched


def test_cancel_unknown_job_id_returns_false_and_touches_no_handle(tmp_path):
    handle = _handle()
    summoner = _FakeSummoner([handle])
    runtime, completions = _runtime(tmp_path, summoner)

    assert runtime.cancel("no-such-job") is False
    assert completions == []
    assert summoner.dismiss_calls == []


def test_cancel_clears_any_pending_attempts_counter_for_that_job(tmp_path):
    handle = _handle()
    handle.status = ContainerStatus.BUSY
    handle.current_job_id = "job1"
    summoner = _FakeSummoner([handle])
    runtime, completions = _runtime(tmp_path, summoner)
    runtime._attempts["job1"] = 2

    runtime.cancel("job1")

    assert "job1" not in runtime._attempts


def test_cancelled_job_bypasses_retry_and_is_never_reinvoked(tmp_path, monkeypatch):
    """Regression test for a real race: cancel() dismisses the container and
    clears _attempts, but the pump thread waiting on that same container's
    socket can independently wake up (its connection just got torn down)
    and call _handle_crash for the very same job_id. Without a guard in
    _handle_crash/_handle_timeout recognizing the handle was already
    cancelled, _retry_or_finalize would see a fresh (cleared) attempts
    counter and silently re-invoke the job the caller explicitly cancelled
    -- directly contradicting cancel()'s own docstring."""
    handle = _handle()
    handle.status = ContainerStatus.BUSY
    handle.current_job_id = "job1"
    summoner = _FakeSummoner([handle])
    runtime, completions = _runtime(tmp_path, summoner, max_retries=3)
    invoked = []
    monkeypatch.setattr(
        runtime, "invoke",
        lambda function_ref, job_id, params: (
            invoked.append((function_ref.id, job_id))
            or Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id, version=function_ref.version))
        ),
    )

    assert runtime.cancel("job1") is True

    # Simulates the pump thread's own crash detection racing in right after.
    inv_handle = InvocationHandle(job_id="job1", function_id="fn1", version=1)
    runtime._handle_crash(handle, inv_handle, "container disconnected (heartbeat timeout)", {})

    time.sleep(0.2)
    assert invoked == []  # never re-invoked
    assert len(completions) == 1
    assert completions[0][1].unwrap_err().name == "JOB_CANCELLED"
