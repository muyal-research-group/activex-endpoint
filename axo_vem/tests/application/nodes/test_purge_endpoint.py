import mongomock
import pytest

from axo_vem.application.nodes.purge_endpoint import PurgeEndpointUseCase
from axo_vem.domain.compute.function import Function
from axo_vem.domain.errors import ConflictError, NotFoundError
from axo_vem.domain.execution.job import Job, JobStatus
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository


class _FakeFunctionRepository:
    def __init__(self, functions=None):
        self._functions = functions or []

    def list_by_endpoint_id(self, endpoint_id):
        return [f for f in self._functions if endpoint_id in f.endpoint_id and f.deleted_at is None]


class _FakeJobRepository:
    def __init__(self, jobs=None):
        self._jobs = jobs or []

    def list_by_function(self, function_id, function_version=None):
        return [
            job for job in self._jobs
            if job.function_id == function_id and (function_version is None or job.function_version == function_version)
        ]


class _FakeEventPublisher:
    def __init__(self):
        self.appended = []

    def append_to_stream(self, stream_name, event_type, data):
        self.appended.append((stream_name, event_type, data))


def _endpoints_collection(doc=None):
    db = mongomock.MongoClient()["test"]
    if doc is not None:
        db["endpoints"].insert_one(doc)
    return db, db["endpoints"]


def _use_case(endpoints, functions=None, jobs=None, activity_repository=None):
    db = mongomock.MongoClient()["test"]
    return PurgeEndpointUseCase(
        endpoints,
        activity_repository or MongoActivityRepository(db["unified_activity"]),
        _FakeFunctionRepository(functions),
        _FakeJobRepository(jobs),
        _FakeEventPublisher(),
    )


def test_execute_raises_not_found_for_unknown_endpoint():
    _, endpoints = _endpoints_collection()
    use_case = _use_case(endpoints)
    with pytest.raises(NotFoundError):
        use_case.execute(endpoint_id="n0")


def test_execute_raises_conflict_when_endpoint_still_running():
    _, endpoints = _endpoints_collection({"_id": "n0", "status": "running"})
    use_case = _use_case(endpoints)
    with pytest.raises(ConflictError):
        use_case.execute(endpoint_id="n0")


def test_execute_purges_endpoint_with_no_functions_exactly_as_before():
    _, endpoints = _endpoints_collection({"_id": "n0", "status": "stopped"})
    use_case = _use_case(endpoints)

    result = use_case.execute(endpoint_id="n0")

    assert result["endpoint_id"] == "n0"
    assert result["functions_marked_deleted"] == 0
    assert result["jobs_force_failed"] == 0
    assert endpoints.find_one({"_id": "n0"}) is None


def test_execute_marks_functions_deleted_with_no_active_jobs():
    _, endpoints = _endpoints_collection({"_id": "n0", "status": "stopped"})
    function = Function(function_id="add", version=1, endpoint_id=["n0"])
    use_case = _use_case(endpoints, functions=[function])

    result = use_case.execute(endpoint_id="n0")

    assert result["functions_marked_deleted"] == 1
    assert result["functions_detached"] == 0
    assert result["jobs_force_failed"] == 0
    event_types = [event_type for _, event_type, _ in use_case._event_publisher.appended]
    assert event_types == ["FunctionDeleted"]


def test_execute_force_fails_only_active_jobs_not_completed_ones():
    _, endpoints = _endpoints_collection({"_id": "n0", "status": "unreachable"})
    function = Function(function_id="add", version=1, endpoint_id=["n0"])
    active_job = Job(job_id="j1", function_id="add", function_version=1, status=JobStatus.QUEUED, endpoint_id="n0")
    finished_job = Job(job_id="j2", function_id="add", function_version=1, status=JobStatus.COMPLETED, endpoint_id="n0")
    use_case = _use_case(endpoints, functions=[function], jobs=[active_job, finished_job])

    result = use_case.execute(endpoint_id="n0")

    assert result["jobs_force_failed"] == 1
    appended = use_case._event_publisher.appended
    job_failed = [data for _, event_type, data in appended if event_type == "JobFailed"]
    assert len(job_failed) == 1
    assert job_failed[0]["job_id"] == "j1"
    function_deleted = [data for _, event_type, data in appended if event_type == "FunctionDeleted"]
    assert len(function_deleted) == 1


def test_execute_skips_already_deleted_functions():
    _, endpoints = _endpoints_collection({"_id": "n0", "status": "stopped"})
    live = Function(function_id="add", version=1, endpoint_id=["n0"])
    already_deleted = Function(function_id="sub", version=1, endpoint_id=["n0"], deleted_at="2026-01-01T00:00:00")
    use_case = _use_case(endpoints, functions=[live, already_deleted])

    result = use_case.execute(endpoint_id="n0")

    assert result["functions_marked_deleted"] == 1
    function_ids = [data["function_id"] for _, event_type, data in use_case._event_publisher.appended if event_type == "FunctionDeleted"]
    assert function_ids == ["add"]


def test_execute_detaches_instead_of_deleting_when_other_endpoints_still_hold_the_function():
    _, endpoints = _endpoints_collection({"_id": "n0", "status": "stopped"})
    function = Function(function_id="add", version=1, endpoint_id=["n0", "n1"])
    use_case = _use_case(endpoints, functions=[function])

    result = use_case.execute(endpoint_id="n0")

    assert result["functions_marked_deleted"] == 0
    assert result["functions_detached"] == 1
    appended = use_case._event_publisher.appended
    event_types = [event_type for _, event_type, _ in appended]
    assert event_types == ["FunctionEndpointDetached"]
    assert appended[0][2]["function_id"] == "add"
    assert appended[0][2]["endpoint_id"] == "n0"


def test_execute_does_not_force_fail_jobs_running_on_a_different_holder_endpoint():
    _, endpoints = _endpoints_collection({"_id": "n0", "status": "stopped"})
    function = Function(function_id="add", version=1, endpoint_id=["n0", "n1"])
    job_on_other_endpoint = Job(job_id="j1", function_id="add", function_version=1, status=JobStatus.QUEUED, endpoint_id="n1")
    use_case = _use_case(endpoints, functions=[function], jobs=[job_on_other_endpoint])

    result = use_case.execute(endpoint_id="n0")

    assert result["jobs_force_failed"] == 0
    event_types = [event_type for _, event_type, _ in use_case._event_publisher.appended]
    assert "JobFailed" not in event_types
