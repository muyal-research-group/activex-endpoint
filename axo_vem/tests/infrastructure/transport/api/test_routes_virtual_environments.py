from xolo.client.models import UserDTO

from .conftest import FAKE_USER, _fake_current_user

OTHER_USER = UserDTO(
    key="user-2", username="bob", first_name="Bob", last_name="B",
    email="bob@example.com", profile_photo="",
)


def _create(client, name="dev-env", cpu=2.0, ram=1024, disk=2048):
    return client.post("/virtual-environments", json={"name": name, "cpu": cpu, "ram": ram, "disk": disk})


def test_create_and_get_virtual_environment(client):
    create_response = _create(client)
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["name"] == "dev-env"
    assert body["owner_user_id"] == FAKE_USER.key
    assert body["resource_quota"] == {"cpu": 2.0, "ram": 1024, "disk": 2048}

    ve_id = body["virtual_environment_id"]
    get_response = client.get(f"/virtual-environments/{ve_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "dev-env"


def test_get_unknown_virtual_environment_returns_404(client):
    response = client.get("/virtual-environments/missing")
    assert response.status_code == 404


def test_list_virtual_environments(client):
    _create(client, name="alpha")
    _create(client, name="beta")

    response = client.get("/virtual-environments")
    assert response.status_code == 200
    names = sorted(doc["name"] for doc in response.json())
    assert names == ["alpha", "beta"]


def test_search_virtual_environments_by_name(client):
    _create(client, name="production-cluster")
    _create(client, name="staging-cluster")
    _create(client, name="sandbox")

    response = client.get("/virtual-environments", params={"name": "cluster"})
    assert response.status_code == 200
    names = sorted(doc["name"] for doc in response.json())
    assert names == ["production-cluster", "staging-cluster"]


def test_update_virtual_environment(client):
    create_response = _create(client)
    ve_id = create_response.json()["virtual_environment_id"]

    update_response = client.put(f"/virtual-environments/{ve_id}", json={
        "name": "renamed-env", "cpu": 4.0, "ram": 2048, "disk": 4096,
    })
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "renamed-env"

    get_response = client.get(f"/virtual-environments/{ve_id}")
    assert get_response.json()["resource_quota"]["cpu"] == 4.0


def test_delete_virtual_environment_soft_deletes(client):
    create_response = _create(client)
    ve_id = create_response.json()["virtual_environment_id"]

    delete_response = client.delete(f"/virtual-environments/{ve_id}")
    assert delete_response.status_code == 204

    get_response = client.get(f"/virtual-environments/{ve_id}")
    assert get_response.status_code == 404

    list_response = client.get("/virtual-environments")
    assert list_response.json() == []


def test_non_owner_gets_403_on_get_update_delete(client):
    create_response = _create(client)
    ve_id = create_response.json()["virtual_environment_id"]

    client.app.dependency_overrides[_fake_current_user] = lambda: OTHER_USER
    try:
        get_response = client.get(f"/virtual-environments/{ve_id}")
        assert get_response.status_code == 403

        put_response = client.put(f"/virtual-environments/{ve_id}", json={
            "name": "x", "cpu": 1.0, "ram": 1, "disk": 1,
        })
        assert put_response.status_code == 403

        delete_response = client.delete(f"/virtual-environments/{ve_id}")
        assert delete_response.status_code == 403
    finally:
        del client.app.dependency_overrides[_fake_current_user]
