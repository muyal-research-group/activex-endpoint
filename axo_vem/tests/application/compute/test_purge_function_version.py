import mongomock
import pytest

from axo_vem.application.compute.purge_function_version import PurgeFunctionVersionUseCase
from axo_vem.domain.errors import ConflictError, NotFoundError
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository


def _use_case():
    db = mongomock.MongoClient()["test"]
    return PurgeFunctionVersionUseCase(db["functions"], MongoActivityRepository(db["unified_activity"])), db


def test_execute_raises_not_found_for_unknown_version():
    use_case, _db = _use_case()
    with pytest.raises(NotFoundError):
        use_case.execute(function_id="add", version=1)


def test_execute_raises_conflict_when_not_soft_deleted_yet():
    use_case, db = _use_case()
    db["functions"].insert_one({"_id": "add:1", "function_id": "add", "version": 1})
    with pytest.raises(ConflictError):
        use_case.execute(function_id="add", version=1)


def test_execute_removes_doc_after_soft_delete():
    use_case, db = _use_case()
    db["functions"].insert_one({
        "_id": "add:1", "function_id": "add", "version": 1, "deleted_at": "2026-01-01T00:00:00+00:00",
    })

    result = use_case.execute(function_id="add", version=1)

    assert result["function_id"] == "add"
    assert result["version"] == 1
    assert db["functions"].find_one({"_id": "add:1"}) is None
