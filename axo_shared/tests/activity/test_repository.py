import threading

from axo_shared.activity.models import ActivityRecord
from axo_shared.activity.repository import InMemoryRepository


def _record(id, function_id="fn1", timestamp=100.0):
    return ActivityRecord(
        id=id, activity_type="JOB_SUBMITTED", function_id=function_id,
        function_version=None, job_id=id, timestamp=timestamp,
    )


def test_save_then_get_round_trips():
    repo = InMemoryRepository()
    repo.save(_record("a"))
    assert repo.get("a") == _record("a")


def test_get_unknown_id_returns_none():
    repo = InMemoryRepository()
    assert repo.get("missing") is None


def test_list_recent_returns_most_recent_first():
    repo = InMemoryRepository()
    repo.save(_record("a", timestamp=1.0))
    repo.save(_record("b", timestamp=2.0))
    repo.save(_record("c", timestamp=3.0))
    recent = repo.list_recent()
    assert [r.id for r in recent] == ["c", "b", "a"]


def test_list_recent_respects_limit():
    repo = InMemoryRepository()
    for i in range(5):
        repo.save(_record(str(i), timestamp=float(i)))
    assert [r.id for r in repo.list_recent(limit=2)] == ["4", "3"]


def test_list_by_function_id_filters_correctly():
    repo = InMemoryRepository()
    repo.save(_record("a", function_id="fn1"))
    repo.save(_record("b", function_id="fn2"))
    repo.save(_record("c", function_id="fn1"))
    matched = repo.list_by_function_id("fn1")
    assert [r.id for r in matched] == ["c", "a"]


def test_bounded_eviction_drops_oldest_and_removes_from_index():
    repo = InMemoryRepository(max_entries=3)
    for i in range(5):
        repo.save(_record(str(i), timestamp=float(i)))
    # Only the last 3 should remain.
    assert [r.id for r in repo.list_recent(limit=10)] == ["4", "3", "2"]
    assert repo.get("0") is None
    assert repo.get("1") is None
    assert repo.get("2") is not None


def test_concurrent_saves_are_thread_safe():
    repo = InMemoryRepository(max_entries=1000)

    def worker(n):
        for i in range(50):
            repo.save(_record(f"{n}-{i}"))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(repo.list_recent(limit=1000)) == 400
