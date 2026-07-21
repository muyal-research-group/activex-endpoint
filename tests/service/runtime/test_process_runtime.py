import queue

from axo_endpoint.service.runtime import WorkerHandle, WorkerRegistry


def test_touch_updates_last_used_and_invocation_count():
    handle = WorkerHandle(function_id="add_one")
    handle.touch(now=100.0)
    assert handle.last_used == 100.0
    assert handle.invocation_count == 1

    handle.touch(now=105.0)
    assert handle.last_used == 105.0
    assert handle.invocation_count == 2


def test_is_idle_boundary():
    handle = WorkerHandle(function_id="add_one")
    handle.touch(now=100.0)

    assert handle.is_idle(ttl_seconds=30.0, now=130.0) is False  # exactly at TTL, not yet idle
    assert handle.is_idle(ttl_seconds=30.0, now=130.1) is True  # just past TTL
    assert handle.is_idle(ttl_seconds=30.0, now=129.9) is False  # well within TTL


def test_exceeded_max_invocations_zero_means_unlimited():
    handle = WorkerHandle(function_id="add_one")
    for _ in range(1000):
        handle.touch(now=0.0)
    assert handle.exceeded_max_invocations(max_invocations=0) is False


def test_exceeded_max_invocations_boundary():
    handle = WorkerHandle(function_id="add_one")
    handle.touch(now=0.0)
    handle.touch(now=0.0)
    assert handle.exceeded_max_invocations(max_invocations=2) is True
    assert handle.exceeded_max_invocations(max_invocations=3) is False


def test_registry_register_and_get_idle_or_none():
    registry = WorkerRegistry()
    assert registry.get_idle_or_none("add_one", None) is None

    handle = WorkerHandle(function_id="add_one")
    registry.register(handle)
    assert registry.get_idle_or_none("add_one", None) is handle


def test_registry_get_idle_or_none_distinguishes_versions():
    """Re-registering a function with a new version must not let invoke()
    reuse the old version's worker -- keying by (function_id, version) is
    the fix for that race."""
    registry = WorkerRegistry()
    v1 = WorkerHandle(function_id="add_one", version=1)
    registry.register(v1)

    assert registry.get_idle_or_none("add_one", 1) is v1
    assert registry.get_idle_or_none("add_one", 2) is None


def test_registry_get_idle_or_none_skips_busy_handles():
    registry = WorkerRegistry()
    handle = WorkerHandle(function_id="add_one")
    handle.busy = True
    registry.register(handle)

    assert registry.get_idle_or_none("add_one", None) is None


def test_registry_pool_holds_multiple_workers_for_one_key():
    registry = WorkerRegistry()
    a = WorkerHandle(function_id="add_one")
    b = WorkerHandle(function_id="add_one")
    registry.register(a)
    registry.register(b)

    assert registry.pool("add_one", None) == [a, b]


def test_registry_least_loaded_picks_shortest_queue():
    registry = WorkerRegistry()
    busier = WorkerHandle(function_id="add_one", request_queue=queue.Queue())
    busier.request_queue.put(("job1", {}))
    idler = WorkerHandle(function_id="add_one", request_queue=queue.Queue())
    registry.register(busier)
    registry.register(idler)

    assert registry.least_loaded("add_one", None) is idler


def test_registry_least_loaded_none_when_pool_empty():
    registry = WorkerRegistry()
    assert registry.least_loaded("add_one", None) is None


def test_registry_evict_removes_specific_handle_only():
    registry = WorkerRegistry()
    a = WorkerHandle(function_id="add_one")
    b = WorkerHandle(function_id="add_one")
    registry.register(a)
    registry.register(b)

    registry.evict(a)

    assert registry.pool("add_one", None) == [b]
    registry.evict(a)  # already gone -- no error
    assert registry.pool("add_one", None) == [b]


def test_registry_evict_last_handle_cleans_up_empty_pool():
    registry = WorkerRegistry()
    handle = WorkerHandle(function_id="add_one")
    registry.register(handle)

    registry.evict(handle)

    assert registry.pool("add_one", None) == []
    assert registry.get_idle_or_none("add_one", None) is None


def test_sweep_idle_evicts_only_handles_past_ttl():
    registry = WorkerRegistry()
    fresh = WorkerHandle(function_id="fresh")
    fresh.touch(now=95.0)
    stale = WorkerHandle(function_id="stale")
    stale.touch(now=50.0)
    registry.register(fresh)
    registry.register(stale)

    evicted = registry.sweep_idle(ttl_seconds=30.0, now=100.0)

    assert evicted == ["stale"]
    assert registry.get_idle_or_none("stale", None) is None
    assert registry.get_idle_or_none("fresh", None) is fresh


def test_sweep_idle_evicts_only_the_specific_idle_pool_member():
    """One busy, one idle-too-long worker in the same function's pool --
    the sweep must only evict the specific stale member, not the whole
    pool."""
    registry = WorkerRegistry()
    busy = WorkerHandle(function_id="add_one")
    busy.busy = True
    busy.touch(now=50.0)
    idle_stale = WorkerHandle(function_id="add_one")
    idle_stale.touch(now=50.0)
    registry.register(busy)
    registry.register(idle_stale)

    evicted = registry.sweep_idle(ttl_seconds=30.0, now=100.0)

    assert evicted == ["add_one"]
    assert registry.pool("add_one", None) == [busy]


def test_sweep_max_invocations_evicts_only_handles_past_cap():
    registry = WorkerRegistry()
    under_cap = WorkerHandle(function_id="under_cap")
    under_cap.touch(now=0.0)
    over_cap = WorkerHandle(function_id="over_cap")
    over_cap.touch(now=0.0)
    over_cap.touch(now=0.0)
    registry.register(under_cap)
    registry.register(over_cap)

    evicted = registry.sweep_max_invocations(max_invocations=2)

    assert evicted == ["over_cap"]
    assert registry.get_idle_or_none("over_cap", None) is None
    assert registry.get_idle_or_none("under_cap", None) is under_cap
