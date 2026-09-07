from option import Ok

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.protocol import Command
from axo_endpoint.core.runtime import FunctionRuntime, InvocationHandle
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey
from axo_endpoint.service.handlers.job_forward import JobForwardHandler
from axo_endpoint.service.handlers.job_submit import JobSubmitHandler


class _FakeRuntime(FunctionRuntime):
    def __init__(self):
        self.invocations = []

    def invoke(self, function_ref, job_id, params):
        self.invocations.append((function_ref, job_id, params))
        return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id))

    def cancel(self, job_id):
        return False


def _registry():
    event_bus = InMemoryEventBus()
    return FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=event_bus), event_bus


def test_job_forward_uses_the_supplied_job_id_verbatim():
    registry, event_bus = _registry()
    runtime = _FakeRuntime()
    handler = JobForwardHandler(
        runtime=runtime, results=InMemoryStorageBackend(), event_bus=event_bus, function_registry=registry,
    )

    result = handler.handle(Command(
        operation="JOB_FORWARD", content_type="application/json",
        envelope={"function_id": "add", "function_version": 1, "job_id": "forwarded-job-1", "params": {"a": 1}},
    ))

    assert result.ok is True
    assert result.metadata == {"job_id": "forwarded-job-1", "status": "QUEUED"}
    assert runtime.invocations == [(StorageKey(id="add", version=1, alias="add"), "forwarded-job-1", {"a": 1})]


def test_job_forward_missing_job_id_returns_error():
    registry, event_bus = _registry()
    handler = JobForwardHandler(
        runtime=_FakeRuntime(), results=InMemoryStorageBackend(), event_bus=event_bus, function_registry=registry,
    )

    result = handler.handle(Command(
        operation="JOB_FORWARD", content_type="application/json",
        envelope={"function_id": "add", "function_version": 1, "params": {}},
    ))

    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"


def test_job_forward_shares_identical_result_shape_with_job_submit():
    registry, event_bus = _registry()
    submit_handler = JobSubmitHandler(
        runtime=_FakeRuntime(), results=InMemoryStorageBackend(), event_bus=event_bus,
        function_registry=registry, job_id_fn=lambda: "same-id",
    )
    forward_handler = JobForwardHandler(
        runtime=_FakeRuntime(), results=InMemoryStorageBackend(), event_bus=event_bus, function_registry=registry,
    )
    envelope = {"function_id": "add", "function_version": 1, "params": {}}

    submit_result = submit_handler.handle(
        Command(operation="JOB_SUBMIT", content_type="application/json", envelope=envelope)
    )
    forward_result = forward_handler.handle(
        Command(operation="JOB_FORWARD", content_type="application/json", envelope={**envelope, "job_id": "same-id"})
    )

    assert submit_result.ok == forward_result.ok
    assert submit_result.metadata == forward_result.metadata
