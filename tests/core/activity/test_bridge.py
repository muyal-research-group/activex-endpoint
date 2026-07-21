from axo_endpoint.core.activity import ActivityTrackingBridge
from axo_shared.activity.models import CONTAINER_READY_EVENT
from axo_endpoint.core.events.bus import Event
from axo_endpoint.core.results import FunctionResult
from axo_endpoint.core.storage import InMemoryStorageBackend
from axo_endpoint.core.storage.backend import StorageKey


class _FakeRepository:
    def __init__(self):
        self.saved = []

    def save(self, entity):
        self.saved.append(entity)

    def get(self, id):
        return next((e for e in self.saved if e.id == id), None)

    def list_recent(self, limit=100):
        return list(reversed(self.saved))[:limit]

    def list_by_function_id(self, function_id, limit=100):
        return [e for e in reversed(self.saved) if e.function_id == function_id][:limit]


def test_on_job_submitted_records_activity():
    repo = _FakeRepository()
    bridge = ActivityTrackingBridge(repository=repo, results=InMemoryStorageBackend())

    bridge.on_job_submitted(Event(
        event_type="JOB_SUBMITTED", payload={"job_id": "job1", "function_id": "fn1"}, timestamp=100.0,
    ))

    assert len(repo.saved) == 1
    record = repo.saved[0]
    assert record.activity_type == "JOB_SUBMITTED"
    assert record.job_id == "job1"
    assert record.function_id == "fn1"
    assert record.failure is None


def test_on_job_finished_fetches_full_result_from_results_store():
    results = InMemoryStorageBackend()
    results.put(StorageKey(id="job1"), FunctionResult(job_id="job1", ok=True, values={"value": 42}))
    repo = _FakeRepository()
    bridge = ActivityTrackingBridge(repository=repo, results=results)

    bridge.on_job_finished(Event(
        event_type="JOB_COMPLETED", payload={"job_id": "job1", "function_id": "fn1"}, timestamp=200.0,
    ))

    assert len(repo.saved) == 1
    record = repo.saved[0]
    assert record.activity_type == "JOB_COMPLETED"
    assert record.failure is None


def test_on_job_finished_records_failure_from_results_store():
    results = InMemoryStorageBackend()
    results.put(StorageKey(id="job2"), FunctionResult(job_id="job2", ok=False, error="boom"))
    repo = _FakeRepository()
    bridge = ActivityTrackingBridge(repository=repo, results=results)

    bridge.on_job_finished(Event(
        event_type="JOB_FAILED", payload={"job_id": "job2", "function_id": "fn1"}, timestamp=200.0,
    ))

    record = repo.saved[0]
    assert record.failure["message"] == "boom"


def test_on_job_finished_missing_result_still_records_activity():
    repo = _FakeRepository()
    bridge = ActivityTrackingBridge(repository=repo, results=InMemoryStorageBackend())

    bridge.on_job_finished(Event(
        event_type="JOB_FAILED", payload={"job_id": "missing", "function_id": "fn1"}, timestamp=200.0,
    ))

    record = repo.saved[0]
    assert record.failure is None


def test_on_container_event_records_activity_with_no_job_id():
    repo = _FakeRepository()
    bridge = ActivityTrackingBridge(repository=repo, results=InMemoryStorageBackend())

    bridge.on_container_event(Event(
        event_type=CONTAINER_READY_EVENT,
        payload={"function_id": "fn1", "version": 2, "service_name": "fn1-svc"},
        timestamp=300.0,
    ))

    assert len(repo.saved) == 1
    record = repo.saved[0]
    assert record.activity_type == CONTAINER_READY_EVENT
    assert record.function_id == "fn1"
    assert record.function_version == 2
    assert record.job_id is None
    assert record.service_name == "fn1-svc"
