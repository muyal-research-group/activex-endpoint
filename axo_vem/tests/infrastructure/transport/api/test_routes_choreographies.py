from xolo.client.models import UserDTO

from .conftest import FAKE_USER, _fake_current_user

OTHER_USER = UserDTO(
    key="user-2", username="bob", first_name="Bob", last_name="B",
    email="bob@example.com", profile_photo="",
)


def _graph(**overrides):
    graph = {
        "nodes": [
            {
                "node_id": "n1", "kind": "function", "position": {"x": 0.0, "y": 0.0},
                "function_id": "add", "function_version": 1,
            },
        ],
        "edges": [],
    }
    graph.update(overrides)
    return graph


def _create(client, name="my-choreography", graph=None):
    return client.post("/choreographies", json={"name": name, "graph": graph or _graph()})


def test_create_and_get_choreography(client):
    create_response = _create(client)
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["name"] == "my-choreography"
    assert body["owner_user_id"] == FAKE_USER.key
    assert body["graph"]["nodes"][0]["function_id"] == "add"

    choreography_id = body["choreography_id"]
    get_response = client.get(f"/choreographies/{choreography_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "my-choreography"
    assert get_response.json()["has_active_run"] is False


def test_get_unknown_choreography_returns_404(client):
    response = client.get("/choreographies/missing")
    assert response.status_code == 404


def test_list_choreographies_scoped_to_owner(client):
    _create(client, name="alpha")
    _create(client, name="beta")

    response = client.get("/choreographies")
    assert response.status_code == 200
    names = sorted(doc["name"] for doc in response.json())
    assert names == ["alpha", "beta"]


def test_update_choreography(client):
    create_response = _create(client)
    choreography_id = create_response.json()["choreography_id"]

    new_graph = _graph(edges=[])
    update_response = client.put(f"/choreographies/{choreography_id}", json={
        "name": "renamed", "graph": new_graph,
    })
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "renamed"

    get_response = client.get(f"/choreographies/{choreography_id}")
    assert get_response.json()["name"] == "renamed"
    # owner_user_id and created_at survive an update untouched.
    assert get_response.json()["owner_user_id"] == FAKE_USER.key
    assert get_response.json()["created_at"] == create_response.json()["created_at"]


def test_update_rejected_while_a_run_is_active(client, choreography_run_repository):
    from axo_vem.domain.choreography.run import ChoreographyRun

    create_response = _create(client)
    choreography_id = create_response.json()["choreography_id"]
    choreography_run_repository.save(ChoreographyRun(run_id="run1", choreography_id=choreography_id, status="running"))

    update_response = client.put(f"/choreographies/{choreography_id}", json={
        "name": "renamed", "graph": _graph(),
    })
    assert update_response.status_code == 409


def test_delete_choreography_soft_deletes(client):
    create_response = _create(client)
    choreography_id = create_response.json()["choreography_id"]

    delete_response = client.delete(f"/choreographies/{choreography_id}")
    assert delete_response.status_code == 204

    get_response = client.get(f"/choreographies/{choreography_id}")
    assert get_response.status_code == 404

    list_response = client.get("/choreographies")
    assert list_response.json() == []


def test_delete_rejected_while_a_run_is_active(client, choreography_run_repository):
    from axo_vem.domain.choreography.run import ChoreographyRun

    create_response = _create(client)
    choreography_id = create_response.json()["choreography_id"]
    choreography_run_repository.save(ChoreographyRun(run_id="run1", choreography_id=choreography_id, status="pending"))

    delete_response = client.delete(f"/choreographies/{choreography_id}")
    assert delete_response.status_code == 409


def test_purge_requires_prior_delete(client):
    create_response = _create(client)
    choreography_id = create_response.json()["choreography_id"]

    purge_response = client.delete(f"/choreographies/{choreography_id}/purge")
    assert purge_response.status_code == 409

    client.delete(f"/choreographies/{choreography_id}")
    purge_response = client.delete(f"/choreographies/{choreography_id}/purge")
    assert purge_response.status_code == 200


def test_validate_route_reports_no_violations_for_a_simple_graph(client):
    create_response = _create(client)
    choreography_id = create_response.json()["choreography_id"]

    response = client.post(f"/choreographies/{choreography_id}/validate")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "violations": []}


def test_validate_route_flags_concurrency_violations(client):
    graph = _graph(
        nodes=[
            {"node_id": "a", "kind": "function", "position": {"x": 0.0, "y": 0.0}, "function_id": "fn-a", "function_version": 1},
            {"node_id": "b", "kind": "function", "position": {"x": 0.0, "y": 0.0}, "function_id": "fn-b", "function_version": 1},
        ],
        edges=[
            {"edge_id": "e1", "source_node_id": "a", "target_node_id": "b", "kind": "fn_to_fn"},
            {"edge_id": "e2", "source_node_id": "a", "target_node_id": "b", "kind": "fn_to_fn"},
        ],
    )
    create_response = _create(client, graph=graph)
    choreography_id = create_response.json()["choreography_id"]

    response = client.post(f"/choreographies/{choreography_id}/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["violations"][0]["node_id"] == "b"
    assert body["violations"][0]["required_concurrency"] == 2


def test_cancel_run_returns_404_for_unknown_run(client):
    response = client.post("/choreographies/c1/runs/missing/cancel")
    assert response.status_code == 404


def test_non_owner_gets_403_on_get_update_delete(client):
    create_response = _create(client)
    choreography_id = create_response.json()["choreography_id"]

    client.app.dependency_overrides[_fake_current_user] = lambda: OTHER_USER
    try:
        get_response = client.get(f"/choreographies/{choreography_id}")
        assert get_response.status_code == 403

        put_response = client.put(f"/choreographies/{choreography_id}", json={
            "name": "x", "graph": _graph(),
        })
        assert put_response.status_code == 403

        delete_response = client.delete(f"/choreographies/{choreography_id}")
        assert delete_response.status_code == 403
    finally:
        del client.app.dependency_overrides[_fake_current_user]
