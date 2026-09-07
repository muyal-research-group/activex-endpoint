import dataclasses

import pytest

from axo_endpoint.core.results import FunctionResult, is_json_safe_value
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey


def test_equality_and_defaults():
    a = FunctionResult(job_id="j1", ok=True)
    b = FunctionResult(job_id="j1", ok=True)
    assert a == b
    assert a.output == {}
    assert a.refs == {}
    assert a.error == ""
    assert a.duration_ms is None
    assert a.warnings == []


def test_is_frozen():
    result = FunctionResult(job_id="j1", ok=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.ok = False


def test_default_values_and_refs_are_not_shared_between_instances():
    a = FunctionResult(job_id="a", ok=True)
    b = FunctionResult(job_id="b", ok=True)
    a.output["x"] = 1
    a.refs["blob"] = StorageKey(id="blob1")
    assert b.output == {}
    assert b.refs == {}


def test_round_trip_with_values_and_refs():
    ref = StorageKey(id="blob1", version=1)
    result = FunctionResult(
        job_id="j1",
        ok=True,
        output={"value": {"sum": 3, "label": "done"}, "type": "json"},
        refs={"output_blob": ref},
    )
    assert result.output["value"]["sum"] == 3
    assert result.refs["output_blob"] == ref


def test_failed_result_carries_error():
    result = FunctionResult(job_id="j1", ok=False, error="boom")
    assert result.ok is False
    assert result.error == "boom"


def test_round_trips_through_in_memory_storage_backend_keyed_by_job_id():
    # Results live in their own StorageBackend[FunctionResult] instance,
    # separate from the function registry's StorageBackend[FunctionRecord]
    # (different lifecycle: one-shot per job_id, no version/alias needed).
    results_store = InMemoryStorageBackend()
    result = FunctionResult(job_id="j1", ok=True, output={"value": {"sum": 3}, "type": "json"})
    key = StorageKey(id="j1")

    results_store.put(key, result)

    assert results_store.get(key).unwrap() == result
    assert results_store.get_by_id("j1").unwrap() == result


@pytest.mark.parametrize(
    "value",
    [
        "text",
        1,
        1.5,
        True,
        None,
        [1, "two", 3.0, None],
        {"a": 1, "b": {"c": [1, 2, 3]}},
    ],
)
def test_is_json_safe_value_true_for_primitives_and_nested_containers(value):
    assert is_json_safe_value(value) is True


@pytest.mark.parametrize(
    "value",
    [
        b"bytes",
        object(),
        {1: "non-string key"},
        [b"bytes-in-list"],
        {"nested": [object()]},
    ],
)
def test_is_json_safe_value_false_for_bytes_and_arbitrary_objects(value):
    assert is_json_safe_value(value) is False
