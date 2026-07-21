import time
from types import SimpleNamespace

import pytest

from axo_shared.activity.models import (
    CONTAINER_CRASHED_EVENT,
    CONTAINER_DISMISSED_EVENT,
    CONTAINER_READY_EVENT,
    CONTAINER_SPAWNED_EVENT,
)
from axo_endpoint.core.events import InMemoryEventBus
from axo_shared.runtime.spec import RuntimeSpec
from axo_endpoint.service.container import spawner as spawner_module
from axo_endpoint.service.container.handle import ContainerHandle, ContainerStatus
from axo_endpoint.service.container.spawner import ContainerSummoner


class _FakeConfig:
    AXO_ENDPOINT_ID = "axo-endpoint-test"
    AXO_ENDPOINT_CONTAINER_JOB_PORT = 5600
    AXO_ENDPOINT_CONTAINER_FASTAPI_PORT = 8000
    AXO_ENDPOINT_CONTAINER_BACKEND = "docker"
    AXO_ENDPOINT_ROUTER_BIND = "tcp://0.0.0.0:5555"
    AXO_ENDPOINT_CONTAINER_RESULT_BIND = "tcp://0.0.0.0:5557"
    AXO_ENDPOINT_DATAIO_TIMEOUT_SECONDS = 30.0
    AXO_ENDPOINT_CONTAINER_NETWORK = "axo-net"
    AXO_ENDPOINT_CONTAINER_PIP_CACHE_VOLUME = "axo-pip-cache"
    AXO_ENDPOINT_CONTAINER_RUNNER_IMAGE = "axo-runner"
    AXO_ENDPOINT_CONTAINER_AUTO_BUILD_IMAGE = True
    AXO_ENDPOINT_CONTAINER_READINESS_TIMEOUT_SECONDS = 0.3
    AXO_ENDPOINT_CONTAINER_MEMORY_LIMIT_BYTES = 1073741824
    AXO_ENDPOINT_CONTAINER_CPU_LIMIT = 1.0


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def summoner(event_bus):
    return ContainerSummoner(config=_FakeConfig(), event_bus=event_bus)


def _handle(function_id="fn1", version=1):
    return ContainerHandle(
        function_id=function_id, version=version, service_name=f"fn-{function_id}-v{version}",
        mode="docker", zmq_address="tcp://x:5600", http_address="http://x:8000",
    )


def _collect(event_bus, event_type):
    received = []
    event_bus.subscribe(event_type, received.append)
    return received


def _wait_for(predicate, timeout=1.0, interval=0.01):
    """Polls until predicate() is true or timeout elapses -- summon()/
    summon_at() now do the real Docker work on a background thread
    (_spawn_in_background), so tests asserting on its side effects
    (run_kwargs, emitted events, handle.status reaching BOOTSTRAPPING)
    can no longer assume it's already done the instant summon() returns."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _FakeContainer:
    id = "container-123"


class _FakeDockerClient:
    def __init__(self):
        self.run_kwargs = {}
        self.images = SimpleNamespace(get=lambda image: object())  # image "exists" -- no build needed
        self.containers = SimpleNamespace(run=self._run)

    def _run(self, **kwargs):
        self.run_kwargs.update(kwargs)
        return _FakeContainer()


def test_summon_emits_container_spawned(summoner, event_bus, monkeypatch):
    received = _collect(event_bus, CONTAINER_SPAWNED_EVENT)
    monkeypatch.setattr(summoner._spawner, "_docker", lambda: _FakeDockerClient())

    result = summoner.summon("fn1", 1, RuntimeSpec(type="container", python_version="3.10"))

    assert result.is_ok
    assert _wait_for(lambda: len(received) == 1)
    assert received[0].payload == {"function_id": "fn1", "version": 1, "service_name": "fn-fn1-v1"}


def test_summon_uses_config_defaults_for_resource_limits(summoner, monkeypatch):
    fake_client = _FakeDockerClient()
    monkeypatch.setattr(summoner._spawner, "_docker", lambda: fake_client)

    summoner.summon("fn1", 1, RuntimeSpec(type="container", python_version="3.10"))

    assert _wait_for(lambda: "mem_limit" in fake_client.run_kwargs)
    assert fake_client.run_kwargs["mem_limit"] == 1073741824
    assert fake_client.run_kwargs["nano_cpus"] == 1_000_000_000


def test_summon_uses_runtime_spec_overrides_for_resource_limits(summoner, monkeypatch):
    fake_client = _FakeDockerClient()
    monkeypatch.setattr(summoner._spawner, "_docker", lambda: fake_client)

    summoner.summon(
        "fn1", 1,
        RuntimeSpec(type="container", python_version="3.10", memory_limit_bytes=268435456, cpu_limit=0.5),
    )

    assert _wait_for(lambda: "mem_limit" in fake_client.run_kwargs)
    assert fake_client.run_kwargs["mem_limit"] == 268435456
    assert fake_client.run_kwargs["nano_cpus"] == 500_000_000


def test_summon_grows_pool_up_to_max_concurrency(summoner, monkeypatch):
    fake_client = _FakeDockerClient()
    monkeypatch.setattr(summoner._spawner, "_docker", lambda: fake_client)
    spec = RuntimeSpec(type="container", python_version="3.10", max_concurrency=3)

    handles = []
    for _ in range(3):
        result = summoner.summon("fn1", 1, spec)
        assert result.is_ok
        handle = result.unwrap()
        # Wait for the background spawn to actually finish (status ->
        # BOOTSTRAPPING) before overwriting it -- otherwise the background
        # thread's own status write can race with (and clobber) the
        # BUSY we're about to set below.
        assert _wait_for(lambda h=handle: h.status == ContainerStatus.BOOTSTRAPPING)
        # Simulate ContainerFunctionRuntime.invoke() synchronously claiming
        # the handle for a job right after summon() returns -- without this,
        # nothing marks the handle busy and the next summon() call would
        # just reuse it instead of growing the pool.
        handle.status = ContainerStatus.BUSY
        handles.append(handle)

    assert {h.service_name for h in handles} == {"fn-fn1-v1", "fn-fn1-v1-p1", "fn-fn1-v1-p2"}
    assert len({id(h) for h in handles}) == 3


def test_summon_reuses_available_pool_member_instead_of_growing(summoner, monkeypatch):
    fake_client = _FakeDockerClient()
    monkeypatch.setattr(summoner._spawner, "_docker", lambda: fake_client)
    spec = RuntimeSpec(type="container", python_version="3.10", max_concurrency=3)

    first = summoner.summon("fn1", 1, spec).unwrap()
    # Wait for the background spawn to reach BOOTSTRAPPING (out of the
    # freshly-reserved STARTING state, which is deliberately excluded from
    # "available") before summoning again, or the second call could see
    # first still STARTING and grow the pool instead of reusing it.
    assert _wait_for(lambda: first.status == ContainerStatus.BOOTSTRAPPING)
    # first is still BOOTSTRAPPING (not busy) -- a second call must reuse
    # it rather than spawn a second container.
    second = summoner.summon("fn1", 1, spec).unwrap()

    assert first is second
    assert fake_client.run_kwargs["name"] == "fn-fn1-v1"


def test_summon_returns_least_busy_member_once_pool_is_at_capacity(summoner, monkeypatch):
    fake_client = _FakeDockerClient()
    monkeypatch.setattr(summoner._spawner, "_docker", lambda: fake_client)
    spec = RuntimeSpec(type="container", python_version="3.10", max_concurrency=2)

    a = summoner.summon("fn1", 1, spec).unwrap()
    assert _wait_for(lambda: a.status == ContainerStatus.BOOTSTRAPPING)
    a.status = ContainerStatus.BUSY
    a.invocation_count = 5

    b = summoner.summon("fn1", 1, spec).unwrap()
    assert b is not a
    assert _wait_for(lambda: b.status == ContainerStatus.BOOTSTRAPPING)
    b.status = ContainerStatus.BUSY
    b.invocation_count = 1

    # Pool is now at capacity (2/2) and both busy -- must not spawn a third,
    # and must hand back whichever has the fewest invocations so far.
    third = summoner.summon("fn1", 1, spec).unwrap()
    assert third is b


def test_summon_default_max_concurrency_names_container_without_pool_suffix(summoner, monkeypatch):
    """max_concurrency defaults to 1 -- pool_index 0's name must be
    unchanged from before pooling existed, a regression check for anyone
    not using this new field."""
    fake_client = _FakeDockerClient()
    monkeypatch.setattr(summoner._spawner, "_docker", lambda: fake_client)

    summoner.summon("fn1", 1, RuntimeSpec(type="container", python_version="3.10"))

    assert _wait_for(lambda: fake_client.run_kwargs.get("name") == "fn-fn1-v1")


def test_poll_readiness_success_emits_container_ready(summoner, event_bus, monkeypatch):
    received = _collect(event_bus, CONTAINER_READY_EVENT)
    fake_response = SimpleNamespace(status_code=200)
    monkeypatch.setattr(spawner_module.requests, "get", lambda url, timeout: fake_response)

    handle = _handle()
    summoner._poll_readiness(handle)

    assert handle.status == ContainerStatus.READY
    assert handle.ready_event.is_set()
    assert len(received) == 1
    assert received[0].payload == {"function_id": "fn1", "version": 1, "service_name": "fn-fn1-v1"}


def test_poll_readiness_timeout_emits_container_crashed(summoner, event_bus, monkeypatch):
    received = _collect(event_bus, CONTAINER_CRASHED_EVENT)

    def always_fails(url, timeout):
        raise spawner_module.requests.RequestException("connection refused")

    monkeypatch.setattr(spawner_module.requests, "get", always_fails)

    handle = _handle()
    summoner._poll_readiness(handle)

    assert handle.status == ContainerStatus.CRASHED
    assert handle.ready_event.is_set()  # "unblock waiters" even on failure
    assert len(received) == 1
    assert received[0].payload == {
        "function_id": "fn1", "version": 1, "service_name": "fn-fn1-v1",
        "error_message": "container did not become ready within 0.3s",
    }


def test_summon_stops_and_removes_stale_crashed_container_before_respawning(summoner, event_bus, monkeypatch):
    """Regression test for the original bug this whole fix chain traces
    back to: a CRASHED handle's underlying container was never actually
    stopped (a crash only ever flips the in-memory status flag), so it
    leaked forever and the next summon() attempt for the same
    (function, version) would 409-conflict trying to recreate a container
    under the same deterministic name. summon() must clean the stale
    handle up first."""
    dismissed = _collect(event_bus, CONTAINER_DISMISSED_EVENT)
    fake_client = _FakeDockerClient()
    monkeypatch.setattr(summoner._spawner, "_docker", lambda: fake_client)

    # No container_id/service_id set -- dismiss()'s stop() call skips the
    # real docker calls entirely and reaches cleanup cleanly (same
    # convention as test_dismiss_emits_container_dismissed above).
    stale = _handle()
    stale.status = ContainerStatus.CRASHED
    with summoner._lock:
        summoner._handles[(stale.function_id, stale.version)] = [stale]

    result = summoner.summon("fn1", 1, RuntimeSpec(type="container", python_version="3.10"))

    assert result.is_ok
    assert len(dismissed) == 1  # the stale container was cleaned up before respawning
    assert stale.status == ContainerStatus.DISMISSED

    new_handle = result.unwrap()
    assert new_handle is not stale
    assert new_handle.service_name == "fn-fn1-v1"  # same name is safe to reuse now that the old one is gone
    assert summoner._handles[("fn1", 1)] == [new_handle]  # stale entry pruned, not left dangling alongside it


def test_dismiss_emits_container_dismissed(summoner, event_bus):
    received = _collect(event_bus, CONTAINER_DISMISSED_EVENT)
    handle = _handle()
    # No container_id/service_id set -- dismiss() skips the real docker calls
    # entirely and reaches the event emission cleanly.
    with summoner._lock:
        summoner._handles[(handle.function_id, handle.version)] = [handle]

    summoner.dismiss(handle)

    assert handle.status == ContainerStatus.DISMISSED
    assert len(received) == 1
    assert received[0].payload == {
        "function_id": "fn1", "version": 1, "service_name": "fn-fn1-v1", "pool_index": 0,
    }


# ── cluster-wide placement: find_idle / least_busy / summon_at / sweep_crashed / pool_summary ──


def test_find_idle_returns_none_when_pool_is_empty(summoner):
    assert summoner.find_idle("fn1", 1) is None


def test_find_idle_returns_available_member_and_ignores_busy_ones(summoner):
    idle = _handle()
    idle.status = ContainerStatus.IDLE
    busy = _handle()
    busy.status = ContainerStatus.BUSY
    with summoner._lock:
        summoner._handles[("fn1", 1)] = [busy, idle]

    assert summoner.find_idle("fn1", 1) is idle


def test_find_idle_ignores_crashed_and_dismissed_members(summoner):
    crashed = _handle()
    crashed.status = ContainerStatus.CRASHED
    with summoner._lock:
        summoner._handles[("fn1", 1)] = [crashed]

    assert summoner.find_idle("fn1", 1) is None


def test_least_busy_returns_member_with_fewest_invocations(summoner):
    a = _handle()
    a.status = ContainerStatus.BUSY
    a.invocation_count = 5
    b = _handle()
    b.status = ContainerStatus.BUSY
    b.invocation_count = 1
    with summoner._lock:
        summoner._handles[("fn1", 1)] = [a, b]

    assert summoner.least_busy("fn1", 1) is b


def test_least_busy_returns_none_for_empty_pool(summoner):
    assert summoner.least_busy("fn1", 1) is None


def test_summon_at_uses_given_pool_index_verbatim(summoner, monkeypatch):
    fake_client = _FakeDockerClient()
    monkeypatch.setattr(summoner._spawner, "_docker", lambda: fake_client)
    spec = RuntimeSpec(type="container", python_version="3.10")

    result = summoner.summon_at("fn1", 1, spec, pool_index=7)

    assert result.is_ok
    handle = result.unwrap()
    assert handle.pool_index == 7
    assert handle.service_name == "fn-fn1-v1-p7"
    assert summoner.list_handles() == [handle]


def test_sweep_crashed_dismisses_immediately(summoner, event_bus):
    dismissed = _collect(event_bus, CONTAINER_DISMISSED_EVENT)
    crashed = _handle()
    crashed.status = ContainerStatus.CRASHED
    healthy = _handle(function_id="fn2")
    healthy.status = ContainerStatus.IDLE
    with summoner._lock:
        summoner._handles[("fn1", 1)] = [crashed]
        summoner._handles[("fn2", 1)] = [healthy]

    evicted = summoner.sweep_crashed()

    assert evicted == ["fn1"]
    assert crashed.status == ContainerStatus.DISMISSED
    assert healthy.status == ContainerStatus.IDLE
    assert len(dismissed) == 1
    assert dismissed[0].payload["pool_index"] == crashed.pool_index


def test_pool_summary_reports_live_and_idle_counts_per_function(summoner):
    idle = _handle()
    idle.status = ContainerStatus.IDLE
    busy = _handle()
    busy.status = ContainerStatus.BUSY
    crashed = _handle()
    crashed.status = ContainerStatus.CRASHED
    with summoner._lock:
        summoner._handles[("fn1", 1)] = [idle, busy, crashed]

    summary = summoner.pool_summary()

    assert summary == {"fn1::1": {"live": 2, "idle": 1}}


class _FakeDockerClientMissingImage:
    """images.get() always misses (as if the tag were never built) --
    images.build() "succeeds" after a short, deliberate delay so concurrent
    _ensure_image() callers have a real window to race in, and counts how
    many times it was actually invoked."""

    def __init__(self, build_delay=0.05):
        import docker.errors
        self._build_delay = build_delay
        self._built = False
        self.build_calls = 0

        def _get(image):
            if not self._built:
                raise docker.errors.ImageNotFound("no such image")
            return object()

        def _build(**kwargs):
            time.sleep(self._build_delay)
            self.build_calls += 1
            self._built = True
            return object(), iter(())

        self.images = SimpleNamespace(get=_get, build=_build)


def test_concurrent_ensure_image_calls_for_same_tag_build_only_once(summoner, monkeypatch):
    """Regression test: before the per-image build lock, N pool members
    cold-starting at once (e.g. max_concurrency=5 with no image built yet)
    each kicked off their own redundant `docker build` of the identical
    tag, starving each other for CPU/disk and often blowing the readiness
    timeout for every one of them."""
    fake_client = _FakeDockerClientMissingImage()
    monkeypatch.setattr(summoner._spawner, "_docker", lambda: fake_client)

    import threading
    results = []

    def _call():
        results.append(summoner._ensure_image("axo-runner:py3.11", "3.11"))

    threads = [threading.Thread(target=_call) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    assert len(results) == 5
    assert all(r.is_ok for r in results)
    assert fake_client.build_calls == 1
