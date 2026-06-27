import pytest
from option import Ok

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.network import Command
from axo_endpoint.core.runtime import FunctionRuntime, InvocationHandle
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey
from axo_endpoint.service.handlers import FunctionRegisterHandler, JobSubmitHandler


class _FakeRuntime(FunctionRuntime):
    def __init__(self):
        self.invocations = []

    def invoke(self, function_ref, job_id, params):
        self.invocations.append((function_ref, job_id, params))
        return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id))


@pytest.fixture
def registry():
    return FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=InMemoryEventBus())


def test_register_then_submit_resolves_the_same_function_ref(registry):
    register_handler = FunctionRegisterHandler(registry=registry, now_fn=lambda: 100.0)
    register_result = register_handler.handle(
        Command(
            operation="FUNCTION_REGISTER",
            content_type="application/octet-stream",
            envelope={"name": "add", "version": 1},
            payload=b"fake-code-bytes",
        )
    )
    assert register_result.ok is True

    runtime = _FakeRuntime()
    submit_handler = JobSubmitHandler(
        runtime=runtime,
        results=InMemoryStorageBackend(),
        event_bus=InMemoryEventBus(),
        job_id_fn=lambda: "job1",
    )
    submit_result = submit_handler.handle(
        Command(
            operation="JOB_SUBMIT",
            content_type="application/json",
            envelope={"function_name": "add", "function_version": 1, "params": {}},
        )
    )

    assert submit_result.ok is True
    function_ref, job_id, _params = runtime.invocations[0]
    assert function_ref == StorageKey(id="add", version=1, alias="add")
    assert job_id == "job1"
