import pytest
from option import Err, Ok

from axo_endpoint.core.events import Event, InMemoryEventBus
from axo_endpoint.core.network import Command
from axo_endpoint.core.runtime import FunctionRuntime, FunctionRuntimeError, InvocationHandle
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey
from axo_endpoint.service.handlers.job_submit import JobSubmitHandler, build_completion_recorder


class _FakeRuntime(FunctionRuntime):
    """Accepts invocations without spawning anything real -- handler tests
    must not need a real subprocess."""

    def __init__(self):
        self.invocations = []

    def invoke(self, function_ref, job_id, params):
        self.invocations.append((function_ref, job_id, params))
        return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id))


class _RejectingRuntime(FunctionRuntime):
    def invoke(self, function_ref, job_id, params):
        return Err(FunctionRuntimeError("no such function"))


@pytest.fixture
def results_store():
    return InMemoryStorageBackend()


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


def test_returns_job_id_and_queued_status_immediately(results_store, event_bus):
    runtime = _FakeRuntime()
    handler = JobSubmitHandler(runtime=runtime, results=results_store, event_bus=event_bus, job_id_fn=lambda: "job1")
    command = Command(
        operation="JOB_SUBMIT",
        content_type="application/json",
        envelope={"function_name": "add", "function_version": 1, "params": {"a": 1, "b": 2}},
    )

    result = handler.handle(command)

    assert result.ok is True
    assert result.metadata == {"job_id": "job1", "status": "QUEUED"}
    assert runtime.invocations == [(StorageKey(id="add", version=1, alias="add"), "job1", {"a": 1, "b": 2})]


def test_writes_pending_placeholder_before_returning(results_store, event_bus):
    handler = JobSubmitHandler(
        runtime=_FakeRuntime(), results=results_store, event_bus=event_bus, job_id_fn=lambda: "job1"
    )
    handler.handle(
        Command(
            operation="JOB_SUBMIT",
            content_type="application/json",
            envelope={"function_name": "add", "function_version": 1, "params": {}},
        )
    )

    placeholder = results_store.get(StorageKey(id="job1")).unwrap()
    assert placeholder.ok is False
    assert placeholder.error == "PENDING"


def test_emits_job_submitted_event(results_store, event_bus):
    received = []
    event_bus.subscribe("JOB_SUBMITTED", received.append)
    handler = JobSubmitHandler(
        runtime=_FakeRuntime(),
        results=results_store,
        event_bus=event_bus,
        job_id_fn=lambda: "job1",
        now_fn=lambda: 100.0,
    )

    handler.handle(
        Command(
            operation="JOB_SUBMIT",
            content_type="application/json",
            envelope={"function_name": "add", "function_version": 1, "params": {}},
        )
    )

    assert received == [
        Event(event_type="JOB_SUBMITTED", payload={"job_id": "job1", "function_id": "add"}, timestamp=100.0)
    ]


def test_runtime_rejection_overwrites_placeholder_with_failure(results_store, event_bus):
    handler = JobSubmitHandler(
        runtime=_RejectingRuntime(), results=results_store, event_bus=event_bus, job_id_fn=lambda: "job1"
    )
    result = handler.handle(
        Command(
            operation="JOB_SUBMIT",
            content_type="application/json",
            envelope={"function_name": "missing", "function_version": 1, "params": {}},
        )
    )

    assert result.ok is False
    placeholder = results_store.get(StorageKey(id="job1")).unwrap()
    assert placeholder.ok is False
    assert placeholder.error != "PENDING"


def test_missing_function_ref_returns_error(results_store, event_bus):
    handler = JobSubmitHandler(runtime=_FakeRuntime(), results=results_store, event_bus=event_bus)
    result = handler.handle(Command(operation="JOB_SUBMIT", content_type="application/json", envelope={}))
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
    assert result.error_code == 1001


def test_completion_recorder_writes_success_result_and_emits_job_completed(results_store):
    event_bus = InMemoryEventBus()
    received = []
    event_bus.subscribe("JOB_COMPLETED", received.append)
    on_complete = build_completion_recorder(results=results_store, event_bus=event_bus, now_fn=lambda: 100.0)

    on_complete(InvocationHandle(job_id="job1", function_id="add"), Ok(5))

    result = results_store.get(StorageKey(id="job1")).unwrap()
    assert result.ok is True
    assert result.values == {"value": 5}
    assert received == [
        Event(event_type="JOB_COMPLETED", payload={"job_id": "job1", "function_id": "add"}, timestamp=100.0)
    ]


def test_completion_recorder_writes_failure_result_and_emits_job_failed(results_store):
    event_bus = InMemoryEventBus()
    received = []
    event_bus.subscribe("JOB_FAILED", received.append)
    on_complete = build_completion_recorder(results=results_store, event_bus=event_bus, now_fn=lambda: 100.0)

    on_complete(InvocationHandle(job_id="job1", function_id="add"), Err(FunctionRuntimeError("boom")))

    result = results_store.get(StorageKey(id="job1")).unwrap()
    assert result.ok is False
    assert result.error == "boom"
    assert len(received) == 1
