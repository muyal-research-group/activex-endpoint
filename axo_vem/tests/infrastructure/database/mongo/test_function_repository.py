import mongomock

from axo_vem.infrastructure.database.mongo.function_repository import MongoFunctionRepository


def _repository():
    db = mongomock.MongoClient()["test"]
    return MongoFunctionRepository(db["functions"])


def test_get_returns_none_for_missing_document():
    repository = _repository()
    assert repository.get("add", 1) is None


def test_get_maps_endpoint_id_and_virtual_environment_id():
    repository = _repository()
    repository._collection.insert_one({
        "_id": "add:1", "function_id": "add", "version": 1,
        "endpoint_id": ["n0"], "virtual_environment_id": "ve1",
    })

    function = repository.get("add", 1)

    assert function.function_id == "add"
    assert function.version == 1
    assert function.endpoint_id == ["n0"]
    assert function.virtual_environment_id == "ve1"


def test_get_defaults_endpoint_id_to_empty_list_when_absent():
    repository = _repository()
    repository._collection.insert_one({"_id": "add:1", "function_id": "add", "version": 1})

    assert repository.get("add", 1).endpoint_id == []


def test_get_is_keyed_by_function_id_and_version_not_just_function_id():
    repository = _repository()
    repository._collection.insert_one({"_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["n0"]})
    repository._collection.insert_one({"_id": "add:2", "function_id": "add", "version": 2, "endpoint_id": ["n1"]})

    assert repository.get("add", 1).endpoint_id == ["n0"]
    assert repository.get("add", 2).endpoint_id == ["n1"]


def test_get_maps_container_status():
    repository = _repository()
    repository._collection.insert_one({
        "_id": "add:1", "function_id": "add", "version": 1, "container_status": "running",
    })

    assert repository.get("add", 1).container_status == "running"


def test_list_by_endpoint_id_returns_only_matching_and_not_yet_deleted_functions():
    repository = _repository()
    repository._collection.insert_many([
        {"_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["n0"]},
        {"_id": "sub:1", "function_id": "sub", "version": 1, "endpoint_id": ["n0"], "deleted_at": "2026-01-01T00:00:00"},
        {"_id": "mul:1", "function_id": "mul", "version": 1, "endpoint_id": ["n1"]},
    ])

    functions = repository.list_by_endpoint_id("n0")

    assert [f.function_id for f in functions] == ["add"]


def test_list_by_endpoint_id_matches_a_function_held_by_multiple_endpoints():
    repository = _repository()
    repository._collection.insert_one(
        {"_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["n0", "n1"]},
    )

    assert [f.function_id for f in repository.list_by_endpoint_id("n0")] == ["add"]
    assert [f.function_id for f in repository.list_by_endpoint_id("n1")] == ["add"]


def test_apply_event_data_adds_endpoint_id_to_the_set_instead_of_overwriting():
    repository = _repository()
    repository.apply_event_data({"function_id": "add", "version": 1, "name": "add", "endpoint_id": "n0"})
    repository.apply_event_data({"function_id": "add", "version": 1, "name": "add", "endpoint_id": "n1"})
    repository.apply_event_data({"function_id": "add", "version": 1, "name": "add", "endpoint_id": "n0"})

    function = repository.get("add", 1)
    assert sorted(function.endpoint_id) == ["n0", "n1"]
    assert function.function_id == "add"


def test_apply_event_data_without_endpoint_id_does_not_touch_the_array():
    repository = _repository()
    repository.apply_event_data({"function_id": "add", "version": 1, "name": "add", "endpoint_id": "n0"})
    repository.apply_event_data({"function_id": "add", "version": 1, "name": "add-renamed"})

    assert repository.get("add", 1).endpoint_id == ["n0"]
    assert repository._collection.find_one({"_id": "add:1"})["name"] == "add-renamed"


def test_detach_endpoint_from_event_removes_only_that_endpoint():
    repository = _repository()
    repository._collection.insert_one(
        {"_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["n0", "n1"]},
    )

    repository.detach_endpoint_from_event({"function_id": "add", "version": 1, "endpoint_id": "n0"})

    assert repository.get("add", 1).endpoint_id == ["n1"]
