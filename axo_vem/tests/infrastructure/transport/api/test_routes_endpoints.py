def test_list_endpoints_empty(client):
    response = client.get("/endpoints")
    assert response.status_code == 200
    assert response.json() == []


def test_list_and_get_endpoint(client, collections):
    collections.endpoints.insert_one({"_id": "n0", "endpoint_id": "n0", "router_bind": "tcp://0.0.0.0:5555"})

    list_response = client.get("/endpoints")
    assert list_response.status_code == 200
    assert list_response.json() == [{
        "endpoint_id": "n0", "router_bind": "tcp://0.0.0.0:5555",
        "purge_eligible": False, "unreachable_since": None,
    }]

    get_response = client.get("/endpoints/n0")
    assert get_response.status_code == 200
    assert get_response.json()["router_bind"] == "tcp://0.0.0.0:5555"
    assert "_id" not in get_response.json()


def test_get_unknown_endpoint_returns_404(client):
    response = client.get("/endpoints/missing")
    assert response.status_code == 404
