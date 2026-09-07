import mongomock

from axo_vem.domain.choreography.choreography import Choreography
from axo_vem.domain.events.models import ChoreographyGraph, ChoreographyNode
from axo_vem.infrastructure.database.mongo.choreography_repository import MongoChoreographyRepository


def _repository():
    db = mongomock.MongoClient()["test"]
    return MongoChoreographyRepository(db["choreographies"]), db["choreographies"]


def _graph():
    return ChoreographyGraph(
        nodes=[ChoreographyNode(node_id="n1", kind="function", position={"x": 0.0, "y": 0.0})], edges=[],
    )


def _choreography(choreography_id="c1", owner="user-1"):
    return Choreography(
        choreography_id=choreography_id, name="pipeline", owner_user_id=owner,
        graph=_graph(), created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )


def test_get_returns_none_for_missing_doc():
    repository, _collection = _repository()
    assert repository.get("no-such-id") is None


def test_get_returns_none_for_soft_deleted_doc():
    repository, collection = _repository()
    repository.save(_choreography())
    repository.soft_delete("c1", "2026-02-01T00:00:00Z")

    assert repository.get("c1") is None
    assert collection.find_one({"_id": "c1"}) is not None  # doc itself still exists


def test_get_returns_choreography_for_existing_non_deleted_doc():
    repository, _collection = _repository()
    repository.save(_choreography())

    result = repository.get("c1")

    assert result.choreography_id == "c1"
    assert result.owner_user_id == "user-1"
    assert result.graph.nodes[0].node_id == "n1"


def test_list_filters_out_soft_deleted_and_scopes_by_owner():
    repository, _collection = _repository()
    repository.save(_choreography(choreography_id="c1", owner="user-1"))
    repository.save(_choreography(choreography_id="c2", owner="user-1"))
    repository.save(_choreography(choreography_id="c3", owner="user-2"))
    repository.soft_delete("c2", "2026-02-01T00:00:00Z")

    all_active = {c.choreography_id for c in repository.list()}
    assert all_active == {"c1", "c3"}

    user_1_only = {c.choreography_id for c in repository.list(owner_user_id="user-1")}
    assert user_1_only == {"c1"}


def test_save_upserts_by_choreography_id():
    repository, collection = _repository()
    repository.save(_choreography(choreography_id="c1"))
    updated = _choreography(choreography_id="c1")
    updated.name = "renamed"
    repository.save(updated)

    assert collection.count_documents({"_id": "c1"}) == 1
    assert repository.get("c1").name == "renamed"


def test_soft_delete_sets_deleted_at_without_removing_the_doc():
    repository, collection = _repository()
    repository.save(_choreography())

    repository.soft_delete("c1", "2026-02-01T00:00:00Z")

    doc = collection.find_one({"_id": "c1"})
    assert doc is not None
    assert doc["deleted_at"] == "2026-02-01T00:00:00Z"
