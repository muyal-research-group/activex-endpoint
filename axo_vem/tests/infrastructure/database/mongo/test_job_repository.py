import mongomock

from axo_vem.domain.execution.job import Job, JobStatus
from axo_vem.infrastructure.database.mongo.job_repository import MongoJobRepository


def _repository():
    db = mongomock.MongoClient()["test"]
    return MongoJobRepository(db["jobs"])


def test_get_returns_none_when_missing():
    repository = _repository()
    assert repository.get("missing") is None


def test_save_then_get_round_trips():
    repository = _repository()
    repository.save(Job(
        job_id="j1", function_id="add", status=JobStatus.QUEUED,
        function_version=1, params={"a": 1, "b": 2},
    ))

    job = repository.get("j1")
    assert job.function_id == "add"
    assert job.status == JobStatus.QUEUED
    assert job.function_version == 1
    assert job.params == {"a": 1, "b": 2}


def test_save_is_idempotent_upsert():
    repository = _repository()
    repository.save(Job(job_id="j1", function_id="add", status=JobStatus.QUEUED))
    repository.save(Job(job_id="j1", function_id="add", status=JobStatus.STARTED, function_version=1))

    job = repository.get("j1")
    assert job.status == JobStatus.STARTED
    assert job.function_version == 1
