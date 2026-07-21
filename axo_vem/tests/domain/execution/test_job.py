from axo_vem.domain.execution.job import Job, JobStatus


def test_start_transitions_to_started():
    job = Job(job_id="j1", function_id="add", status=JobStatus.QUEUED)
    job.start()
    assert job.status == JobStatus.STARTED


def test_complete_transitions_to_completed_and_sets_duration():
    job = Job(job_id="j1", function_id="add", status=JobStatus.STARTED)
    job.complete(duration_ms=42.5)
    assert job.status == JobStatus.COMPLETED
    assert job.duration_ms == 42.5


def test_fail_transitions_to_failed():
    job = Job(job_id="j1", function_id="add", status=JobStatus.STARTED)
    job.fail()
    assert job.status == JobStatus.FAILED


def test_to_dict_reflects_all_fields():
    job = Job(
        job_id="j1", function_id="add", status=JobStatus.COMPLETED,
        function_version=2, duration_ms=100.0, params={"a": 1},
        endpoint_id="n0", created_at="2026-01-01T00:00:00+00:00",
    )
    assert job.to_dict() == {
        "job_id": "j1",
        "function_id": "add",
        "status": "COMPLETED",
        "function_version": 2,
        "duration_ms": 100.0,
        "params": {"a": 1},
        "endpoint_id": "n0",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
