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


def test_registry_register_and_get_or_none():
    registry = WorkerRegistry()
    assert registry.get_or_none("add_one") is None

    handle = WorkerHandle(function_id="add_one")
    registry.register(handle)
    assert registry.get_or_none("add_one") is handle


def test_registry_evict_removes_and_returns_handle():
    registry = WorkerRegistry()
    handle = WorkerHandle(function_id="add_one")
    registry.register(handle)

    evicted = registry.evict("add_one")
    assert evicted is handle
    assert registry.get_or_none("add_one") is None
    assert registry.evict("add_one") is None  # already gone, no error


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
    assert registry.get_or_none("stale") is None
    assert registry.get_or_none("fresh") is fresh


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
    assert registry.get_or_none("over_cap") is None
    assert registry.get_or_none("under_cap") is under_cap
