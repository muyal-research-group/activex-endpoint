from option import Err, Ok

from axo_endpoint.core.consensus.concurrency import SlotDecision
from axo_endpoint.core.errors import ContainerError
from axo_endpoint.core.storage.backend import StorageKey
from axo_endpoint.service.container.handle import ContainerHandle, ContainerStatus
from axo_endpoint.service.runtime.container_runtime import ContainerFunctionRuntime
from axo_shared.runtime.spec import RuntimeSpec


class _FakeConfig:
    def __init__(self, scratch_root: str):
        self.AXO_ENDPOINT_SCRATCH_ROOT = scratch_root


class _FakeRecord:
    def __init__(self, spec):
        self.runtime_spec = spec


class _FakeRegistry:
    def __init__(self, spec):
        self._spec = spec

    def get(self, function_ref):
        return Ok(_FakeRecord(self._spec))


def _handle(pool_index=0):
    h = ContainerHandle(
        function_id="fn1", version=1, service_name=f"fn1-svc-{pool_index}",
        mode="docker", zmq_address="tcp://127.0.0.1:1", http_address="http://x",
        pool_index=pool_index,
    )
    h.ready_event.set()
    h.status = ContainerStatus.IDLE
    return h


class _FakeSummoner:
    """Duck-types the subset of ContainerSummoner's cluster-placement API
    invoke() calls -- controlled per test rather than exercising real
    Docker/pool logic (that's ContainerSummoner's own test suite's job)."""

    def __init__(self, idle=None, least_busy=None, summon_at_handle=None, summon_at_error=None):
        self._idle = idle
        self._least_busy = least_busy
        self._summon_at_handle = summon_at_handle
        self._summon_at_error = summon_at_error
        self.summon_at_calls = []

    def find_idle(self, function_id, version):
        return self._idle

    def least_busy(self, function_id, version):
        return self._least_busy

    def summon_at(self, function_id, version, spec, pool_index):
        self.summon_at_calls.append(pool_index)
        if self._summon_at_error is not None:
            return Err(self._summon_at_error)
        return Ok(self._summon_at_handle)


class _LegacySummoner:
    """Only implements the pre-cluster-placement summon() -- exercises the
    "attach_cluster_placement was never called" fallback path."""

    def __init__(self, handle):
        self._handle = handle

    def summon(self, function_id, version, spec):
        return Ok(self._handle)


class _FakeConcurrencyClient:
    def __init__(self, decision, self_id="self-endpoint"):
        self._decision = decision
        self.self_id = self_id
        self.requests = []
        self.releases = []

    def request_growth(self, function_id, version, max_concurrency):
        self.requests.append((function_id, version, max_concurrency))
        return Ok(self._decision)

    def release(self, function_id, version, slot_index):
        self.releases.append((function_id, version, slot_index))


def _runtime(tmp_path, summoner):
    return ContainerFunctionRuntime(
        function_registry=_FakeRegistry(RuntimeSpec(type="container", max_concurrency=2)),
        summoner=summoner,
        on_complete=lambda *a: None,
        config=_FakeConfig(str(tmp_path)),
    )


def _no_pump(monkeypatch, runtime):
    """invoke() dispatches by starting a real pump thread that connects to
    handle.zmq_address -- these tests only care about which handle got
    picked, not the ZMQ protocol itself (that's test_container_runtime_zmq.py's job)."""
    monkeypatch.setattr(runtime, "_ensure_pump", lambda handle: None)


def test_local_reuse_skips_the_leader_entirely(tmp_path, monkeypatch):
    idle_handle = _handle()
    summoner = _FakeSummoner(idle=idle_handle)
    runtime = _runtime(tmp_path, summoner)
    _no_pump(monkeypatch, runtime)
    concurrency_client = _FakeConcurrencyClient(SlotDecision.granted(0))
    runtime.attach_cluster_placement(concurrency_client, forward_job_fn=lambda *a: Ok(None))

    result = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {})

    assert result.is_ok
    assert concurrency_client.requests == []  # never asked -- local reuse handled it
    assert idle_handle.invocation_count == 1


def test_granted_grows_locally_at_the_assigned_index(tmp_path, monkeypatch):
    grown_handle = _handle(pool_index=1)
    summoner = _FakeSummoner(idle=None, summon_at_handle=grown_handle)
    runtime = _runtime(tmp_path, summoner)
    _no_pump(monkeypatch, runtime)
    concurrency_client = _FakeConcurrencyClient(SlotDecision.granted(1))
    runtime.attach_cluster_placement(concurrency_client, forward_job_fn=lambda *a: Ok(None))

    result = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {})

    assert result.is_ok
    assert summoner.summon_at_calls == [1]
    assert grown_handle.invocation_count == 1


def test_granted_slot_is_released_back_when_summon_at_fails(tmp_path):
    """Regression test: if the leader grants a slot but the actual container
    spawn then fails (Docker conflict, image error, ...), the grant must not
    be left dangling -- otherwise every future job for this function gets
    routed back to a slot that was never backed by a real container, and
    least_busy() finds nothing forever."""
    summoner = _FakeSummoner(idle=None, summon_at_error=ContainerError("409 conflict"))
    runtime = _runtime(tmp_path, summoner)
    concurrency_client = _FakeConcurrencyClient(SlotDecision.granted(1))
    runtime.attach_cluster_placement(concurrency_client, forward_job_fn=lambda *a: Ok(None))

    result = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {})

    assert result.is_err
    assert concurrency_client.releases == [("fn1", 1, 1)]


def test_place_targeting_self_queues_behind_least_busy_local_member(tmp_path, monkeypatch):
    local_handle = _handle()
    summoner = _FakeSummoner(idle=None, least_busy=local_handle)
    runtime = _runtime(tmp_path, summoner)
    _no_pump(monkeypatch, runtime)
    concurrency_client = _FakeConcurrencyClient(SlotDecision.place("self-endpoint"), self_id="self-endpoint")
    runtime.attach_cluster_placement(concurrency_client, forward_job_fn=lambda *a: Ok(None))

    result = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {})

    assert result.is_ok
    assert local_handle.invocation_count == 1


def test_place_targeting_another_endpoint_forwards_and_dispatches_nothing_locally(tmp_path):
    summoner = _FakeSummoner(idle=None)
    runtime = _runtime(tmp_path, summoner)
    concurrency_client = _FakeConcurrencyClient(SlotDecision.place("other-endpoint"), self_id="self-endpoint")
    forwarded = []
    on_forwarded = []

    def forward_job_fn(target, function_ref, job_id, params):
        forwarded.append((target, job_id))
        return Ok(None)

    def record_forwarded(job_id, target_endpoint_id):
        on_forwarded.append((job_id, target_endpoint_id))

    runtime.attach_cluster_placement(concurrency_client, forward_job_fn=forward_job_fn, on_forwarded=record_forwarded)

    result = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {})

    assert result.is_ok
    assert forwarded == [("other-endpoint", "job1")]
    assert on_forwarded == [("job1", "other-endpoint")]


def test_retry_surfaces_as_a_retryable_error(tmp_path):
    summoner = _FakeSummoner(idle=None)
    runtime = _runtime(tmp_path, summoner)
    concurrency_client = _FakeConcurrencyClient(SlotDecision.retry())
    runtime.attach_cluster_placement(concurrency_client, forward_job_fn=lambda *a: Ok(None))

    result = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {})

    assert result.is_err


def test_without_attach_cluster_placement_falls_back_to_legacy_summon(tmp_path, monkeypatch):
    """No attach_cluster_placement() call at all -- must behave exactly like
    before cluster placement existed, no matter what a fake summoner's other
    methods would have returned."""
    legacy_handle = _handle()
    runtime = _runtime(tmp_path, _LegacySummoner(legacy_handle))
    _no_pump(monkeypatch, runtime)

    result = runtime.invoke(StorageKey(id="fn1", version=1), "job1", {})

    assert result.is_ok
    assert legacy_handle.invocation_count == 1
