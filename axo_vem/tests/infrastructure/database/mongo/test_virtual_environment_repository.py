import mongomock

from axo_vem.domain.workspace.value_objects import ResourceCapacity
from axo_vem.domain.workspace.virtual_environment import VirtualEnvironment
from axo_vem.infrastructure.database.mongo.virtual_environment_repository import (
    MongoVirtualEnvironmentRepository,
)


def _repository():
    db = mongomock.MongoClient()["test"]
    return MongoVirtualEnvironmentRepository(db["virtual_environments"])


def test_get_returns_none_for_missing_document():
    repository = _repository()
    assert repository.get("missing") is None


def test_get_returns_none_for_soft_deleted_document():
    repository = _repository()
    repository._collection.insert_one({
        "_id": "ve1", "virtual_environment_id": "ve1", "name": "dev", "owner_user_id": "u1",
        "deleted_at": 100.0, "resource_quota": {"cpu": 1.0, "ram": 1, "disk": 1},
    })
    assert repository.get("ve1") is None


def test_list_filters_out_soft_deleted_and_scopes_by_owner():
    repository = _repository()
    quota = {"cpu": 1.0, "ram": 1, "disk": 1}
    repository._collection.insert_many([
        {"_id": "ve1", "virtual_environment_id": "ve1", "name": "a", "owner_user_id": "u1", "deleted_at": None, "resource_quota": quota},
        {"_id": "ve2", "virtual_environment_id": "ve2", "name": "b", "owner_user_id": "u2", "deleted_at": None, "resource_quota": quota},
        {"_id": "ve3", "virtual_environment_id": "ve3", "name": "c", "owner_user_id": "u1", "deleted_at": 1.0, "resource_quota": quota},
    ])

    assert {v.virtual_environment_id for v in repository.list()} == {"ve1", "ve2"}
    assert {v.virtual_environment_id for v in repository.list(owner_user_id="u1")} == {"ve1"}


def test_search_by_name_is_case_insensitive_partial_match():
    repository = _repository()
    quota = {"cpu": 1.0, "ram": 1, "disk": 1}
    repository._collection.insert_many([
        {"_id": "ve1", "virtual_environment_id": "ve1", "name": "Production-Cluster", "owner_user_id": "u1", "deleted_at": None, "resource_quota": quota},
        {"_id": "ve2", "virtual_environment_id": "ve2", "name": "sandbox", "owner_user_id": "u1", "deleted_at": None, "resource_quota": quota},
    ])

    results = repository.search_by_name("cluster")
    assert [v.virtual_environment_id for v in results] == ["ve1"]


def test_save_then_get_round_trips():
    repository = _repository()
    repository.save(VirtualEnvironment("ve1", "dev", "u1", ResourceCapacity(2.0, 1024, 2048)))

    ve = repository.get("ve1")
    assert ve.name == "dev" and ve.owner_user_id == "u1" and ve.capacity.cpu == 2.0


def test_soft_delete_hides_from_get_and_list():
    repository = _repository()
    repository.save(VirtualEnvironment("ve1", "dev", "u1", ResourceCapacity(2.0, 1024, 2048)))
    repository.soft_delete("ve1", "2026-01-01T00:00:00Z")

    assert repository.get("ve1") is None
    assert repository.list() == []
