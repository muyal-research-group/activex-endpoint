from datetime import datetime, timedelta, timezone

import mongomock

from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository
from axo_vem.infrastructure.database.mongo.activity_retention_worker import ActivityRetentionWorker


def _repo():
    collection = mongomock.MongoClient()["test"]["unified_activity"]
    return MongoActivityRepository(collection)


def _insert(repo, event_id, created_at):
    repo._collection.insert_one({
        "_id": event_id, "event_type": "SomeEvent", "created_at": created_at,
        "user_id": None, "virtual_environment_id": None, "endpoint_id": None,
        "runtime_type": None, "meta": {},
    })


def test_tick_purges_rows_older_than_the_retention_ceiling():
    repo = _repo()
    _insert(repo, "old", datetime.now(timezone.utc) - timedelta(hours=2))
    _insert(repo, "new", datetime.now(timezone.utc))

    worker = ActivityRetentionWorker(activity_repository=repo, retention_hours=1.0)
    worker.tick()

    remaining_ids = {e["event_id"] for e in repo.get_timeline()}
    assert remaining_ids == {"new"}


def test_tick_with_nothing_old_purges_nothing():
    repo = _repo()
    _insert(repo, "new", datetime.now(timezone.utc))

    worker = ActivityRetentionWorker(activity_repository=repo, retention_hours=1.0)
    worker.tick()

    assert {e["event_id"] for e in repo.get_timeline()} == {"new"}


def test_stop_ends_run_forever_after_one_tick(monkeypatch):
    repo = _repo()
    worker = ActivityRetentionWorker(activity_repository=repo, retention_hours=1.0, tick_seconds=0.0)

    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        worker.stop()

    monkeypatch.setattr(
        "axo_vem.infrastructure.database.mongo.activity_retention_worker.time.sleep", fake_sleep,
    )
    worker.run_forever()

    assert sleep_calls == [0.0]


def test_tick_purges_superseded_function_updated_rows():
    repo = _repo()
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    repo._collection.insert_one({
        "_id": "u1", "event_type": "FunctionUpdated", "created_at": old,
        "user_id": None, "virtual_environment_id": None, "endpoint_id": None,
        "runtime_type": None, "meta": {"function_id": "add", "version": 1},
    })
    repo._collection.insert_one({
        "_id": "u2", "event_type": "FunctionUpdated", "created_at": old + timedelta(minutes=1),
        "user_id": None, "virtual_environment_id": None, "endpoint_id": None,
        "runtime_type": None, "meta": {"function_id": "add", "version": 1},
    })

    worker = ActivityRetentionWorker(activity_repository=repo, retention_hours=1.0)
    worker.tick()

    remaining_ids = {e["event_id"] for e in repo.get_timeline()}
    assert remaining_ids == {"u2"}  # u1 superseded and old enough; u2 is the group's newest


def test_tick_does_not_raise_when_the_repository_errors():
    repo = _repo()

    class _BoomRepo:
        def purge_older_than(self, cutoff):
            raise RuntimeError("mongo is down")

    worker = ActivityRetentionWorker(activity_repository=_BoomRepo(), retention_hours=1.0)
    worker.tick()  # must not raise
