import mongomock

from axo_vem.infrastructure.database.mongo.endpoint_repository import MongoEndpointRepository


def _repository():
    db = mongomock.MongoClient()["test"]
    return MongoEndpointRepository(db["endpoints"])


def test_get_returns_none_for_missing_document():
    repository = _repository()
    assert repository.get("missing") is None


def test_get_maps_virtual_environment_id_and_last_seen_at():
    repository = _repository()
    repository._collection.insert_one({
        "_id": "n0", "router_bind": "tcp://0.0.0.0:5555",
        "virtual_environment_id": "ve1", "created_at": "2026-01-02T00:00:00",
    })

    endpoint = repository.get("n0")

    assert endpoint.virtual_environment_id == "ve1"
    assert endpoint.last_seen_at == "2026-01-02T00:00:00"


def test_get_maps_pub_bind_and_status():
    repository = _repository()
    repository._collection.insert_one({
        "_id": "n0", "router_bind": "tcp://0.0.0.0:5555", "pub_bind": "tcp://0.0.0.0:5556",
        "status": "running",
    })

    endpoint = repository.get("n0")

    assert endpoint.pub_bind == "tcp://0.0.0.0:5556"
    assert endpoint.status == "running"


def test_list_by_virtual_environment_maps_pub_bind_and_status():
    repository = _repository()
    repository._collection.insert_one({
        "_id": "n0", "router_bind": "tcp://0.0.0.0:5555", "virtual_environment_id": "ve1",
        "created_at": "2026-01-01T00:00:00", "pub_bind": "tcp://0.0.0.0:5556", "status": "unreachable",
    })

    endpoints = repository.list_by_virtual_environment("ve1")

    assert endpoints[0].pub_bind == "tcp://0.0.0.0:5556"
    assert endpoints[0].status == "unreachable"


def test_list_by_virtual_environment_orders_most_recently_seen_first():
    repository = _repository()
    repository._collection.insert_many([
        {"_id": "n0", "router_bind": "tcp://0.0.0.0:5555", "virtual_environment_id": "ve1", "created_at": "2026-01-01T00:00:00"},
        {"_id": "n1", "router_bind": "tcp://0.0.0.0:5555", "virtual_environment_id": "ve1", "created_at": "2026-01-03T00:00:00"},
        {"_id": "n2", "router_bind": "tcp://0.0.0.0:5555", "virtual_environment_id": "ve1", "created_at": "2026-01-02T00:00:00"},
        {"_id": "n3", "router_bind": "tcp://0.0.0.0:5555", "virtual_environment_id": "ve-other", "created_at": "2026-01-04T00:00:00"},
    ])

    endpoints = repository.list_by_virtual_environment("ve1")

    assert [e.endpoint_id for e in endpoints] == ["n1", "n2", "n0"]


def test_list_by_virtual_environment_tie_breaks_by_endpoint_id_ascending():
    repository = _repository()
    repository._collection.insert_many([
        {"_id": "n9", "router_bind": "tcp://0.0.0.0:5555", "virtual_environment_id": "ve1", "created_at": "2026-01-01T00:00:00"},
        {"_id": "n1", "router_bind": "tcp://0.0.0.0:5555", "virtual_environment_id": "ve1", "created_at": "2026-01-01T00:00:00"},
    ])

    endpoints = repository.list_by_virtual_environment("ve1")

    assert [e.endpoint_id for e in endpoints] == ["n1", "n9"]


def test_list_by_virtual_environment_excludes_detached_endpoints():
    """EndpointVirtualEnvironmentDetached's event leaves virtual_environment_id
    at its EventEnvelope default of None -- the projector's $set upsert nulls
    the doc's field, so a detached endpoint must not appear here."""
    repository = _repository()
    repository._collection.insert_one({
        "_id": "n0", "router_bind": "tcp://0.0.0.0:5555", "virtual_environment_id": None, "created_at": "2026-01-01T00:00:00",
    })

    assert repository.list_by_virtual_environment("ve1") == []
