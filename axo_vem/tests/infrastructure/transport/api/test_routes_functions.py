def test_list_functions_empty(client):
    response = client.get("/functions")
    assert response.status_code == 200
    assert response.json() == []


def test_get_function_returns_all_versions(client, collections):
    collections.functions.insert_one({"_id": "add:1", "function_id": "add", "version": 1, "state": "REGISTERED"})
    collections.functions.insert_one({"_id": "add:2", "function_id": "add", "version": 2, "state": "REGISTERED"})
    collections.functions.insert_one({"_id": "sub:1", "function_id": "sub", "version": 1, "state": "REGISTERED"})

    response = client.get("/functions/add")
    assert response.status_code == 200
    versions = sorted(doc["version"] for doc in response.json())
    assert versions == [1, 2]


def test_get_unknown_function_returns_404(client):
    response = client.get("/functions/missing")
    assert response.status_code == 404
