import pytest

from axo_endpoint.core.consensus.dirty_tracker import DirtyTracker
from axo_endpoint.core.consensus.registry_sync import (
    RegistrySyncBridge,
    deserialize_function_record,
    serialize_function_record,
)
from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.functions.lifecycle import FunctionState
from axo_shared.functions.models import FunctionRecord
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


@pytest.fixture
def dirty_tracker():
    return DirtyTracker(max_dirty_count=50)


@pytest.fixture
def bridge(registry, backend, dirty_tracker, event_bus):
    bridge = RegistrySyncBridge(
        registry=registry, backend=backend, dirty_tracker=dirty_tracker, now_fn=lambda: 42.0
    )
    event_bus.subscribe(FunctionState.REGISTERED.value, bridge.on_function_event)
    event_bus.subscribe("FUNCTION_UPDATED", bridge.on_function_updated)
    return bridge


def test_on_function_event_marks_the_registered_key_dirty(registry, dirty_tracker, bridge):
    registry.register(function_id="foo", name="foo", code=b"print(1)", now=1.0)

    mutation = dirty_tracker.drain()
    assert set(mutation.function_changes.keys()) == {"foo:1"}

    record = deserialize_function_record(mutation.function_changes["foo:1"])
    assert record.function_id == "foo"
    assert record.name == "foo"
    assert record.version == 1
    assert record.code == b"print(1)"


def test_on_function_updated_marks_the_same_key_dirty_with_new_env_vars(registry, dirty_tracker, bridge):
    key = registry.register(function_id="foo", name="foo", code=b"print(1)", now=1.0).unwrap()
    dirty_tracker.drain()  # clear the register's own dirty mark first

    registry.update(key, now=2.0, env_vars={"A": "1"})

    mutation = dirty_tracker.drain()
    assert set(mutation.function_changes.keys()) == {"foo:1"}
    record = deserialize_function_record(mutation.function_changes["foo:1"])
    assert record.runtime_spec.env_vars == {"A": "1"}


def test_apply_incoming_writes_record_into_backend_without_re_marking_dirty(bridge, backend, dirty_tracker):
    record = FunctionRecord(
        code=b"print(2)",
        function_id="bar",
        name="bar",
        version=1,
        created_at=5.0,
        state=FunctionState.REGISTERED,
        runtime_spec=None,
    )
    blob = serialize_function_record(record)
    bridge.apply_incoming({"bar:1": blob})

    stored = backend.get(StorageKey(id="bar", version=1, alias="bar")).unwrap()
    assert stored == record

    # apply_incoming bypasses FunctionRegistry.register(), so no event fires
    # and the dirty tracker stays empty.
    mutation = dirty_tracker.drain()
    assert mutation.function_changes == {}


def test_apply_incoming_emits_function_replicated_event_when_event_bus_given(backend, dirty_tracker):
    from axo_shared.activity.models import FUNCTION_REPLICATED_EVENT

    bus = InMemoryEventBus()
    received = []
    bus.subscribe(FUNCTION_REPLICATED_EVENT, received.append)
    bridge = RegistrySyncBridge(
        registry=FunctionRegistry(backend=backend, event_bus=bus), backend=backend,
        dirty_tracker=dirty_tracker, now_fn=lambda: 42.0, event_bus=bus,
    )
    record = FunctionRecord(
        code=b"print(2)", function_id="bar", name="bar", version=1, created_at=5.0,
        state=FunctionState.REGISTERED, runtime_spec=None,
    )
    bridge.apply_incoming({"bar:1": serialize_function_record(record)})

    assert len(received) == 1
    assert received[0].event_type == FUNCTION_REPLICATED_EVENT
    assert received[0].payload == {"function_id": "bar", "version": 1}


def test_apply_incoming_does_not_emit_for_tombstones(backend, dirty_tracker):
    from axo_shared.activity.models import FUNCTION_REPLICATED_EVENT
    from axo_endpoint.core.consensus.registry_sync import serialize_function_tombstone

    bus = InMemoryEventBus()
    received = []
    bus.subscribe(FUNCTION_REPLICATED_EVENT, received.append)
    bridge = RegistrySyncBridge(
        registry=FunctionRegistry(backend=backend, event_bus=bus), backend=backend,
        dirty_tracker=dirty_tracker, now_fn=lambda: 42.0, event_bus=bus,
    )
    bridge.apply_incoming({"bar:1": serialize_function_tombstone()})

    assert received == []


def test_serialize_then_deserialize_round_trips_runtime_spec():
    spec = RuntimeSpec(type="container", python_version="3.10", requirements=["numpy"], image="my-image")
    record = FunctionRecord(
        code=b"code-bytes", function_id="baz", name="baz", version=2, created_at=9.0,
        state=FunctionState.REGISTERED, runtime_spec=spec,
    )
    blob = serialize_function_record(record)
    round_tripped = deserialize_function_record(blob)
    assert round_tripped == record


def test_serialize_then_deserialize_round_trips_params_schema():
    schema = [ParamSpec(name="a", type="number", required=True), ParamSpec(name="b", type="json", required=False)]
    record = FunctionRecord(
        code=b"code-bytes", function_id="baz", name="baz", version=2, created_at=9.0,
        state=FunctionState.REGISTERED, params_schema=schema,
    )
    blob = serialize_function_record(record)
    round_tripped = deserialize_function_record(blob)
    assert round_tripped == record


def test_serialize_then_deserialize_round_trips_code_format():
    record = FunctionRecord(
        code=b"source-bytes", function_id="qux", name="qux", version=1, created_at=3.0,
        state=FunctionState.REGISTERED, code_format="source",
    )
    blob = serialize_function_record(record)
    round_tripped = deserialize_function_record(blob)
    assert round_tripped.code_format == "source"
    assert round_tripped == record
