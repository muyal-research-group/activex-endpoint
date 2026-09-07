import mongomock
import pytest

from axo_vem.application.choreography.purge_choreography import PurgeChoreographyUseCase
from axo_vem.domain.errors import ConflictError, NotFoundError, NotOwnerError
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository


def _use_case():
    db = mongomock.MongoClient()["test"]
    return (
        PurgeChoreographyUseCase(
            db["choreographies"], db["choreography_runs"], MongoActivityRepository(db["unified_activity"]),
        ),
        db,
    )


def test_execute_raises_not_found_for_unknown_choreography():
    use_case, _db = _use_case()
    with pytest.raises(NotFoundError):
        use_case.execute(choreography_id="c1", current_user_id="user-1")


def test_execute_raises_not_owner_for_foreign_choreography():
    use_case, db = _use_case()
    db["choreographies"].insert_one({
        "_id": "c1", "owner_user_id": "user-1", "deleted_at": "2026-01-01T00:00:00+00:00",
    })

    with pytest.raises(NotOwnerError):
        use_case.execute(choreography_id="c1", current_user_id="someone-else")


def test_execute_raises_conflict_when_not_soft_deleted_yet():
    use_case, db = _use_case()
    db["choreographies"].insert_one({"_id": "c1", "owner_user_id": "user-1"})

    with pytest.raises(ConflictError):
        use_case.execute(choreography_id="c1", current_user_id="user-1")


def test_execute_deletes_choreography_run_docs_and_activity_rows_on_success():
    use_case, db = _use_case()
    db["choreographies"].insert_one({
        "_id": "c1", "owner_user_id": "user-1", "deleted_at": "2026-01-01T00:00:00+00:00",
    })
    db["choreography_runs"].insert_many([
        {"_id": "run1", "choreography_id": "c1"},
        {"_id": "run2", "choreography_id": "c1"},
    ])
    db["unified_activity"].insert_one({"_id": "act1", "meta": {"choreography_id": "c1"}})

    use_case.execute(choreography_id="c1", current_user_id="user-1")

    assert db["choreographies"].find_one({"_id": "c1"}) is None
    assert db["choreography_runs"].count_documents({"choreography_id": "c1"}) == 0
    assert db["unified_activity"].count_documents({}) == 0
