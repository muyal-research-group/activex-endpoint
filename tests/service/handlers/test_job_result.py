import pytest

from axo_shared.protocol import Command
from axo_endpoint.core.results import FunctionResult
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey
from axo_endpoint.service.handlers import JobResultHandler


@pytest.fixture
def results_store():
    return InMemoryStorageBackend()


def test_pending_status_for_in_flight_job(results_store):
    results_store.put(StorageKey(id="job1"), FunctionResult(job_id="job1", ok=False, error="PENDING"))
    handler = JobResultHandler(results=results_store)

    result = handler.handle(Command(operation="JOB_RESULT", content_type="application/json", envelope={"job_id": "job1"}))

    assert result.ok is True
    assert result.metadata == {"job_id": "job1", "status": "PENDING"}


def test_not_found_for_unknown_job(results_store):
    handler = JobResultHandler(results=results_store)
    result = handler.handle(
        Command(operation="JOB_RESULT", content_type="application/json", envelope={"job_id": "unknown"})
    )
    assert result.ok is False
    assert result.error_name == "JOB_NOT_FOUND"
    assert result.error_code == 2002


def test_missing_job_id_returns_error(results_store):
    handler = JobResultHandler(results=results_store)
    result = handler.handle(Command(operation="JOB_RESULT", content_type="application/json", envelope={}))
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
    assert result.error_code == 1001


def test_returns_completed_result(results_store):
    results_store.put(StorageKey(id="job1"), FunctionResult(job_id="job1", ok=True, values={"value": 5}))
    handler = JobResultHandler(results=results_store)

    result = handler.handle(Command(operation="JOB_RESULT", content_type="application/json", envelope={"job_id": "job1"}))

    assert result.ok is True
    assert result.metadata["status"] == "COMPLETED"
    assert result.metadata["result_ok"] is True
    assert result.metadata["values"] == {"value": 5}


def test_returns_failed_result(results_store):
    results_store.put(StorageKey(id="job1"), FunctionResult(job_id="job1", ok=False, error="boom"))
    handler = JobResultHandler(results=results_store)

    result = handler.handle(Command(operation="JOB_RESULT", content_type="application/json", envelope={"job_id": "job1"}))

    assert result.ok is True
    assert result.metadata["status"] == "FAILED"
    assert result.metadata["result_ok"] is False
    assert result.metadata["error"] == "boom"
