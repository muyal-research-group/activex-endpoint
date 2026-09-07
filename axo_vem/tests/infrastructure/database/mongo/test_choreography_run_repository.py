import mongomock
import pytest

from axo_vem.domain.choreography.run import ChoreographyRun, NodeRunState
from axo_vem.infrastructure.database.mongo.choreography_run_repository import MongoChoreographyRunRepository


def _repository():
    db = mongomock.MongoClient()["test"]
    return MongoChoreographyRunRepository(db["choreography_runs"]), db["choreography_runs"]


def test_get_returns_none_for_missing_run():
    repository, _collection = _repository()
    assert repository.get("no-such-run") is None


def test_list_by_choreography_sorted_by_started_at_descending():
    repository, _collection = _repository()
    repository.save(ChoreographyRun(run_id="run1", choreography_id="c1", started_at="2026-01-01T00:00:00Z"))
    repository.save(ChoreographyRun(run_id="run2", choreography_id="c1", started_at="2026-01-03T00:00:00Z"))
    repository.save(ChoreographyRun(run_id="run3", choreography_id="c1", started_at="2026-01-02T00:00:00Z"))
    repository.save(ChoreographyRun(run_id="run4", choreography_id="other", started_at="2026-01-04T00:00:00Z"))

    runs = repository.list_by_choreography("c1")

    assert [r.run_id for r in runs] == ["run2", "run3", "run1"]


@pytest.mark.parametrize("status,expected", [
    ("pending", True), ("running", True),
    ("completed", False), ("failed", False), ("cancelled", False),
])
def test_has_active_run_true_only_for_pending_or_running_statuses(status, expected):
    repository, _collection = _repository()
    repository.save(ChoreographyRun(run_id="run1", choreography_id="c1", status=status))

    assert repository.has_active_run("c1") is expected


def test_has_active_run_false_for_choreography_with_no_runs():
    repository, _collection = _repository()
    assert repository.has_active_run("no-such-choreography") is False


def test_save_upserts_by_run_id_and_round_trips_node_states():
    repository, collection = _repository()
    node_state = NodeRunState(
        node_id="n1", status="completed", job_id="job1", endpoint_id="ep1",
        attempt=2, error=None, warnings=["slow"], duration_ms=12.5,
    )
    run = ChoreographyRun(
        run_id="run1", choreography_id="c1", status="running",
        node_states={"n1": node_state}, started_at="2026-01-01T00:00:00Z",
    )

    repository.save(run)
    assert collection.count_documents({"_id": "run1"}) == 1

    loaded = repository.get("run1")
    assert loaded.run_id == "run1"
    assert loaded.node_states["n1"] == node_state

    run.status = "completed"
    run.finished_at = "2026-01-01T00:05:00Z"
    repository.save(run)

    assert collection.count_documents({"_id": "run1"}) == 1  # still one doc, not a duplicate
    reloaded = repository.get("run1")
    assert reloaded.status == "completed"
    assert reloaded.finished_at == "2026-01-01T00:05:00Z"
