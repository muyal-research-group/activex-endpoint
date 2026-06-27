import pytest

from axo_endpoint.core.events import Event, InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry, FunctionState
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def backend():
    return InMemoryStorageBackend()


@pytest.fixture
def registry(backend, event_bus):
    return FunctionRegistry(backend=backend, event_bus=event_bus)


def test_register_then_get_round_trips_record(registry):
    result = registry.register(name="add_one", version=1, code=b"code-bytes", now=100.0)
    assert result.is_ok
    key = result.unwrap()
    assert key == StorageKey(id="add_one", version=1, alias="add_one")

    record = registry.get(key).unwrap()
    assert record.name == "add_one"
    assert record.version == 1
    assert record.code == b"code-bytes"
    assert record.created_at == 100.0
    assert record.state == FunctionState.REGISTERED


def test_register_emits_registered_event(registry, event_bus):
    received = []
    event_bus.subscribe(FunctionState.REGISTERED.value, received.append)

    registry.register(name="add_one", version=1, code=b"code", now=100.0)

    assert received == [
        Event(
            event_type="REGISTERED",
            payload={"function_id": "add_one", "version": 1},
            timestamp=100.0,
        )
    ]


def test_register_same_name_different_versions_backend_resolves_latest(registry, backend):
    registry.register(name="add_one", version=1, code=b"v1", now=100.0)
    registry.register(name="add_one", version=2, code=b"v2", now=200.0)

    latest = backend.get_by_id("add_one").unwrap()
    assert latest.code == b"v2"

    latest_by_alias = backend.get_by_alias("add_one").unwrap()
    assert latest_by_alias.code == b"v2"


def test_get_on_nonexistent_key_returns_ok_none(registry):
    result = registry.get(StorageKey(id="missing"))
    assert result.is_ok
    assert result.unwrap() is None


def test_transition_on_valid_edge_updates_state_and_emits_event(registry, event_bus):
    key = registry.register(name="add_one", version=1, code=b"code", now=100.0).unwrap()
    received = []
    event_bus.subscribe(FunctionState.COLD_START.value, received.append)

    result = registry.transition(key, FunctionState.COLD_START, now=101.0)

    assert result.is_ok
    updated = result.unwrap()
    assert updated.state == FunctionState.COLD_START
    assert registry.get(key).unwrap().state == FunctionState.COLD_START
    assert received == [
        Event(event_type="COLD_START", payload={"function_id": "add_one", "version": 1}, timestamp=101.0)
    ]


def test_transition_on_invalid_edge_returns_err_without_mutating_or_emitting(registry, event_bus):
    key = registry.register(name="add_one", version=1, code=b"code", now=100.0).unwrap()
    received = []
    event_bus.subscribe(FunctionState.RUNNING.value, received.append)

    result = registry.transition(key, FunctionState.RUNNING, now=101.0)  # REGISTERED -> RUNNING is invalid

    assert result.is_err
    assert registry.get(key).unwrap().state == FunctionState.REGISTERED
    assert received == []


def test_transition_on_missing_key_returns_err(registry):
    result = registry.transition(StorageKey(id="missing"), FunctionState.COLD_START, now=100.0)
    assert result.is_err
