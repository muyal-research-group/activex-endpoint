import pytest

from axo_endpoint.core.events import Event, InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.functions.lifecycle import FunctionState
from axo_shared.functions.params_schema import ParamSpec
from axo_shared.runtime.spec import RuntimeSpec
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
    result = registry.register(function_id="add_one", name="add_one", code=b"code-bytes", now=100.0)
    assert result.is_ok
    key = result.unwrap()
    assert key == StorageKey(id="add_one", version=1, alias="add_one")

    record = registry.get(key).unwrap()
    assert record.function_id == "add_one"
    assert record.name == "add_one"
    assert record.version == 1
    assert record.code == b"code-bytes"
    assert record.created_at == 100.0
    assert record.state == FunctionState.REGISTERED


def test_register_emits_registered_event(registry, event_bus):
    received = []
    event_bus.subscribe(FunctionState.REGISTERED.value, received.append)

    registry.register(function_id="add_one", name="add_one", code=b"code", now=100.0)

    assert received == [
        Event(
            event_type="REGISTERED",
            payload={"function_id": "add_one", "version": 1},
            timestamp=100.0,
        )
    ]


def test_register_same_function_id_auto_increments_version(registry, backend):
    first = registry.register(function_id="add_one", name="add_one", code=b"v1", now=100.0).unwrap()
    second = registry.register(function_id="add_one", name="add_one", code=b"v2", now=200.0).unwrap()

    assert first.version == 1
    assert second.version == 2

    latest = backend.get_by_id("add_one").unwrap()
    assert latest.code == b"v2"

    latest_by_alias = backend.get_by_alias("add_one").unwrap()
    assert latest_by_alias.code == b"v2"


def test_register_different_function_id_starts_its_own_version_lineage(registry):
    registry.register(function_id="a", name="add_one", code=b"a-v1", now=100.0)
    registry.register(function_id="a", name="add_one", code=b"a-v2", now=200.0)
    other = registry.register(function_id="b", name="add_one", code=b"b-v1", now=300.0).unwrap()

    # Same display name, different function_id (e.g. a different user/VE) --
    # its own independent version lineage, unaffected by "a"'s history.
    assert other.version == 1


def test_get_on_nonexistent_key_returns_ok_none(registry):
    result = registry.get(StorageKey(id="missing"))
    assert result.is_ok
    assert result.unwrap() is None


def test_transition_on_valid_edge_updates_state_and_emits_event(registry, event_bus):
    key = registry.register(function_id="add_one", name="add_one", code=b"code", now=100.0).unwrap()
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
    key = registry.register(function_id="add_one", name="add_one", code=b"code", now=100.0).unwrap()
    received = []
    event_bus.subscribe(FunctionState.RUNNING.value, received.append)

    result = registry.transition(key, FunctionState.RUNNING, now=101.0)  # REGISTERED -> RUNNING is invalid

    assert result.is_err
    assert registry.get(key).unwrap().state == FunctionState.REGISTERED
    assert received == []


def test_transition_on_missing_key_returns_err(registry):
    result = registry.transition(StorageKey(id="missing"), FunctionState.COLD_START, now=100.0)
    assert result.is_err


def test_update_merges_new_params_schema_additively(registry):
    key = registry.register(
        function_id="add_one", name="add_one", code=b"code", now=100.0,
        params_schema=[ParamSpec(name="a", type="number", required=True)],
    ).unwrap()

    result = registry.update(
        key, now=101.0,
        params_schema=[
            ParamSpec(name="a", type="string", required=False),  # same name -- left untouched
            ParamSpec(name="b", type="number", required=False, default=1),  # new -- appended
        ],
    )

    assert result.is_ok
    updated = result.unwrap()
    assert [p.name for p in updated.params_schema] == ["a", "b"]
    assert updated.params_schema[0].type == "number"  # original "a" preserved, not overwritten
    assert registry.get(key).unwrap().params_schema == updated.params_schema


def test_update_merges_env_vars_into_existing_runtime_spec(registry):
    key = registry.register(
        function_id="add_one", name="add_one", code=b"code", now=100.0,
        runtime_spec=RuntimeSpec(env_vars={"A": "1"}),
    ).unwrap()

    result = registry.update(key, now=101.0, env_vars={"B": "2"})

    assert result.is_ok
    assert result.unwrap().runtime_spec.env_vars == {"A": "1", "B": "2"}


def test_update_creates_runtime_spec_when_none_existed(registry):
    key = registry.register(function_id="add_one", name="add_one", code=b"code", now=100.0).unwrap()

    result = registry.update(key, now=101.0, env_vars={"A": "1"})

    assert result.is_ok
    assert result.unwrap().runtime_spec.env_vars == {"A": "1"}


def test_update_emits_updated_event(registry, event_bus):
    key = registry.register(function_id="add_one", name="add_one", code=b"code", now=100.0).unwrap()
    received = []
    event_bus.subscribe("FUNCTION_UPDATED", received.append)

    registry.update(key, now=101.0, env_vars={"A": "1"})

    assert received == [
        Event(event_type="FUNCTION_UPDATED", payload={"function_id": "add_one", "version": 1}, timestamp=101.0)
    ]


def test_update_on_missing_key_returns_err(registry):
    result = registry.update(StorageKey(id="missing", version=1), now=100.0, env_vars={"A": "1"})
    assert result.is_err


def test_update_with_no_changes_is_a_no_op_that_still_emits(registry, event_bus):
    key = registry.register(function_id="add_one", name="add_one", code=b"code", now=100.0).unwrap()
    received = []
    event_bus.subscribe("FUNCTION_UPDATED", received.append)

    result = registry.update(key, now=101.0)

    assert result.is_ok
    assert result.unwrap().params_schema is None
    assert result.unwrap().runtime_spec is None
    assert len(received) == 1
