from option import Ok

from axo_endpoint.core.runtime import FunctionRuntime, InvocationHandle
from axo_endpoint.service.handlers.job_cancel import JobCancelHandler
from axo_shared.protocol import Command


class _FakeRuntime(FunctionRuntime):
    def __init__(self, cancel_result: bool = True):
        self.cancel_calls = []
        self._cancel_result = cancel_result

    def invoke(self, function_ref, job_id, params):
        return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id))

    def cancel(self, job_id):
        self.cancel_calls.append(job_id)
        return self._cancel_result


def test_cancel_returns_ok_and_cancelled_status_when_runtime_confirms():
    runtime = _FakeRuntime(cancel_result=True)
    handler = JobCancelHandler(runtime=runtime)

    result = handler.handle(Command(
        operation="JOB_CANCEL", content_type="application/json", envelope={"job_id": "job1"},
    ))

    assert result.ok is True
    assert result.metadata == {"job_id": "job1", "status": "CANCELLED"}
    assert runtime.cancel_calls == ["job1"]


def test_cancel_returns_job_not_found_error_when_runtime_returns_false():
    runtime = _FakeRuntime(cancel_result=False)
    handler = JobCancelHandler(runtime=runtime)

    result = handler.handle(Command(
        operation="JOB_CANCEL", content_type="application/json", envelope={"job_id": "unknown-job"},
    ))

    assert result.ok is False
    assert result.error_name == "JOB_NOT_FOUND"
    assert result.metadata == {"job_id": "unknown-job"}


def test_cancel_missing_job_id_returns_missing_field_error():
    runtime = _FakeRuntime()
    handler = JobCancelHandler(runtime=runtime)

    result = handler.handle(Command(
        operation="JOB_CANCEL", content_type="application/json", envelope={},
    ))

    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
    assert runtime.cancel_calls == []
