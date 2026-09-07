import pytest
from option import Ok

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.runtime import FunctionRuntime, InvocationHandle
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey
from axo_endpoint.service.runtime.dispatcher import RuntimeDispatcher
from axo_shared.runtime.spec import RuntimeSpec


class _FakeRuntime(FunctionRuntime):
    def __init__(self, cancel_result: bool = False):
        self.invocations = []
        self.cancel_calls = []
        self._cancel_result = cancel_result

    def invoke(self, function_ref, job_id, params):
        self.invocations.append((function_ref, job_id, params))
        return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id))

    def cancel(self, job_id):
        self.cancel_calls.append(job_id)
        return self._cancel_result


def _registry():
    return FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=InMemoryEventBus())


def test_invoke_routes_to_process_runtime_by_default():
    registry = _registry()
    key = registry.register(function_id="add", name="add", code=b"code", now=0.0).unwrap()
    process_runtime, container_runtime = _FakeRuntime(), _FakeRuntime()
    dispatcher = RuntimeDispatcher(registry=registry, process_runtime=process_runtime, container_runtime=container_runtime)

    result = dispatcher.invoke(key, "job1", {"a": 1})

    assert result.is_ok
    assert process_runtime.invocations == [(key, "job1", {"a": 1})]
    assert container_runtime.invocations == []


def test_invoke_routes_to_container_runtime_when_spec_type_is_container():
    registry = _registry()
    key = registry.register(
        function_id="add", name="add", code=b"code", now=0.0,
        runtime_spec=RuntimeSpec(type="container"),
    ).unwrap()
    process_runtime, container_runtime = _FakeRuntime(), _FakeRuntime()
    dispatcher = RuntimeDispatcher(registry=registry, process_runtime=process_runtime, container_runtime=container_runtime)

    result = dispatcher.invoke(key, "job1", {"a": 1})

    assert result.is_ok
    assert container_runtime.invocations == [(key, "job1", {"a": 1})]
    assert process_runtime.invocations == []


def test_invoke_returns_invocation_error_when_function_not_found_in_registry():
    registry = _registry()
    process_runtime, container_runtime = _FakeRuntime(), _FakeRuntime()
    dispatcher = RuntimeDispatcher(registry=registry, process_runtime=process_runtime, container_runtime=container_runtime)

    result = dispatcher.invoke(StorageKey(id="missing", version=1), "job1", {})

    assert result.is_err
    assert result.unwrap_err().name == "INVOCATION_FAILED"
    assert process_runtime.invocations == []
    assert container_runtime.invocations == []


@pytest.mark.parametrize(
    "process_result, container_result, expected",
    [
        (True, False, True),
        (False, True, True),
        (True, True, True),
        (False, False, False),
    ],
)
def test_cancel_tries_both_runtimes_and_returns_true_if_either_finds_it(process_result, container_result, expected):
    registry = _registry()
    process_runtime = _FakeRuntime(cancel_result=process_result)
    container_runtime = _FakeRuntime(cancel_result=container_result)
    dispatcher = RuntimeDispatcher(registry=registry, process_runtime=process_runtime, container_runtime=container_runtime)

    assert dispatcher.cancel("job1") is expected
    # Neither call short-circuits the other -- a job only ever lives on one
    # runtime, but the dispatcher can't know which without asking both.
    assert process_runtime.cancel_calls == ["job1"]
    assert container_runtime.cancel_calls == ["job1"]
