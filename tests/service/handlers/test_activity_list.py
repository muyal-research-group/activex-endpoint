from axo_shared.activity.models import ActivityRecord
from axo_shared.activity.repository import InMemoryRepository
from axo_shared.protocol import Command
from axo_endpoint.service.handlers import ActivityListHandler


def _record(id, function_id="fn1", timestamp=100.0):
    return ActivityRecord(
        id=id, activity_type="JOB_SUBMITTED", function_id=function_id,
        function_version=None, job_id=id, timestamp=timestamp,
    )


def test_activity_list_returns_recent_records_by_default():
    repo = InMemoryRepository()
    repo.save(_record("a", timestamp=1.0))
    repo.save(_record("b", timestamp=2.0))
    handler = ActivityListHandler(repository=repo)

    result = handler.handle(Command(operation="ACTIVITY_LIST", content_type="application/json", envelope={}))

    assert result.ok is True
    assert [r["id"] for r in result.metadata["records"]] == ["b", "a"]


def test_activity_list_filters_by_function_id():
    repo = InMemoryRepository()
    repo.save(_record("a", function_id="fn1"))
    repo.save(_record("b", function_id="fn2"))
    handler = ActivityListHandler(repository=repo)

    result = handler.handle(Command(
        operation="ACTIVITY_LIST", content_type="application/json", envelope={"function_id": "fn2"},
    ))

    assert [r["id"] for r in result.metadata["records"]] == ["b"]


def test_activity_list_respects_limit():
    repo = InMemoryRepository()
    for i in range(5):
        repo.save(_record(str(i), timestamp=float(i)))
    handler = ActivityListHandler(repository=repo)

    result = handler.handle(Command(
        operation="ACTIVITY_LIST", content_type="application/json", envelope={"limit": 2},
    ))

    assert len(result.metadata["records"]) == 2
