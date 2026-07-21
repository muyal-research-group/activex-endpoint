from fastapi import FastAPI
from fastapi.testclient import TestClient

from axo_vem.application.compute.purge_function_version import PurgeFunctionVersionUseCase
from axo_vem.infrastructure.transport.api.controllers import functions as functions_routes

from .conftest import _fake_current_user


def _create_ve(client, name="dev-env", cpu=2.0, ram=1024, disk=2048):
    return client.post("/virtual-environments", json={"name": name, "cpu": cpu, "ram": ram, "disk": disk})


def test_delete_virtual_environment_with_endpoint_assigned_returns_409(client, collections):
    ve_id = _create_ve(client).json()["virtual_environment_id"]
    collections.endpoints.insert_one({"_id": "n0", "endpoint_id": "n0", "virtual_environment_id": ve_id})

    response = client.delete(f"/virtual-environments/{ve_id}")
    assert response.status_code == 409

    # Unassigning the endpoint clears the guard.
    collections.endpoints.update_one({"_id": "n0"}, {"$set": {"virtual_environment_id": None}})
    response = client.delete(f"/virtual-environments/{ve_id}")
    assert response.status_code == 204


def test_purge_virtual_environment_requires_soft_delete_first(client):
    ve_id = _create_ve(client).json()["virtual_environment_id"]

    response = client.delete(f"/virtual-environments/{ve_id}/purge")
    assert response.status_code == 409

    client.delete(f"/virtual-environments/{ve_id}")
    response = client.delete(f"/virtual-environments/{ve_id}/purge")
    assert response.status_code == 200

    assert client.get(f"/virtual-environments/{ve_id}").status_code == 404


def test_purge_virtual_environment_removes_activity(client, activity_repository):
    ve_id = _create_ve(client).json()["virtual_environment_id"]
    activity_repository.record("SomeEvent", {
        "event_id": "e1", "created_at": "2026-01-01T00:00:00+00:00",
        "virtual_environment_id": ve_id,
    })

    client.delete(f"/virtual-environments/{ve_id}")
    client.delete(f"/virtual-environments/{ve_id}/purge")

    assert activity_repository.get_timeline(virtual_environment_id=ve_id) == []


def test_purge_virtual_environment_unknown_returns_404(client):
    response = client.delete("/virtual-environments/missing/purge")
    assert response.status_code == 404


def test_purge_function_version_requires_soft_delete_first(client, collections):
    collections.functions.insert_one({"_id": "add:1", "function_id": "add", "version": 1})

    response = client.delete("/functions/add/1/purge")
    assert response.status_code == 409

    collections.functions.update_one({"_id": "add:1"}, {"$set": {"deleted_at": "2026-01-01T00:00:00+00:00"}})
    response = client.delete("/functions/add/1/purge")
    assert response.status_code == 200

    assert client.get("/functions/add").status_code == 404


def test_purge_function_version_removes_only_that_versions_activity(client, collections, activity_repository):
    collections.functions.insert_one({
        "_id": "add:1", "function_id": "add", "version": 1, "deleted_at": "2026-01-01T00:00:00+00:00",
    })
    activity_repository.record("FunctionRegistered", {
        "event_id": "e1", "created_at": "2026-01-01T00:00:00+00:00",
        "function_id": "add", "function_version": 1,
    })
    activity_repository.record("FunctionRegistered", {
        "event_id": "e2", "created_at": "2026-01-01T00:00:00+00:00",
        "function_id": "add", "function_version": 2,
    })

    response = client.delete("/functions/add/1/purge")
    assert response.status_code == 200
    assert response.json()["purged_activity_count"] == 1

    remaining = activity_repository.get_timeline(function_id="add")
    assert len(remaining) == 1
    assert remaining[0]["event_id"] == "e2"


def test_purge_function_version_unknown_returns_404(client):
    response = client.delete("/functions/missing/1/purge")
    assert response.status_code == 404


class _FakeStreamAdmin:
    def __init__(self):
        self.deleted = []

    def delete_stream(self, stream_name):
        self.deleted.append(stream_name)


def test_purge_function_version_deletes_its_own_kurrent_stream(collections, activity_repository):
    """The Kurrent stream is per (function_id, version) -- purging one
    version must delete exactly that stream, not some other version's."""
    collections.functions.insert_one({
        "_id": "add:1", "function_id": "add", "version": 1, "deleted_at": "2026-01-01T00:00:00+00:00",
    })
    stream_admin = _FakeStreamAdmin()
    purge_use_case = PurgeFunctionVersionUseCase(collections.functions, activity_repository, stream_admin)
    router = functions_routes.build_router(
        collections.functions, _fake_current_user,
        register_use_case=None, delete_use_case=None, update_use_case=None,
        purge_use_case=purge_use_case,
    )
    app = FastAPI()
    app.include_router(router)
    local_client = TestClient(app)

    response = local_client.delete("/functions/add/1/purge")

    assert response.status_code == 200
    assert stream_admin.deleted == ["functions-add-1"]


def test_purge_endpoint_requires_stopped_first(client, collections):
    collections.endpoints.insert_one({"_id": "n0", "endpoint_id": "n0", "status": "running"})

    response = client.delete("/endpoints/n0/purge")
    assert response.status_code == 409

    collections.endpoints.update_one({"_id": "n0"}, {"$set": {"status": "stopped"}})
    response = client.delete("/endpoints/n0/purge")
    assert response.status_code == 200

    assert client.get("/endpoints/n0").status_code == 404


def test_purge_endpoint_accepts_unreachable_status_directly(client, collections):
    """Regression test for the widened gate: an unreachable endpoint (found
    dead by EndpointLivenessWorker) is purgeable immediately, without ever
    having to pass through `stopped` first."""
    collections.endpoints.insert_one({"_id": "n0", "endpoint_id": "n0", "status": "unreachable"})

    response = client.delete("/endpoints/n0/purge")
    assert response.status_code == 200
    assert client.get("/endpoints/n0").status_code == 404


def test_purge_endpoint_removes_activity(client, collections, activity_repository):
    collections.endpoints.insert_one({"_id": "n0", "endpoint_id": "n0", "status": "stopped"})
    activity_repository.record("EndpointStopped", {
        "event_id": "e1", "created_at": "2026-01-01T00:00:00+00:00", "endpoint_id": "n0",
    })

    response = client.delete("/endpoints/n0/purge")
    assert response.status_code == 200
    assert response.json()["purged_activity_count"] == 1

    assert activity_repository.get_timeline(endpoint_id="n0") == []


def test_purge_endpoint_unknown_returns_404(client):
    response = client.delete("/endpoints/missing/purge")
    assert response.status_code == 404


def test_purge_endpoint_cascades_soft_delete_to_its_functions(client, collections, db):
    collections.endpoints.insert_one({"_id": "n0", "endpoint_id": "n0", "status": "stopped"})
    collections.functions.insert_one({"_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["n0"]})
    collections.functions.insert_one({"_id": "sub:1", "function_id": "sub", "version": 1, "endpoint_id": ["n1"]})

    response = client.delete("/endpoints/n0/purge")

    assert response.status_code == 200
    assert response.json()["functions_marked_deleted"] == 1
    assert collections.functions.find_one({"_id": "add:1"})["deleted_at"] is not None
    # A function on a different endpoint is untouched.
    assert collections.functions.find_one({"_id": "sub:1"}).get("deleted_at") is None


def test_purge_endpoint_force_fails_the_functions_active_jobs(client, collections, db):
    collections.endpoints.insert_one({"_id": "n0", "endpoint_id": "n0", "status": "unreachable"})
    collections.functions.insert_one({"_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["n0"]})
    db["jobs"].insert_one({
        "_id": "j1", "job_id": "j1", "function_id": "add", "function_version": 1,
        "status": "QUEUED", "endpoint_id": "n0",
    })

    response = client.delete("/endpoints/n0/purge")

    assert response.status_code == 200
    assert response.json()["jobs_force_failed"] == 1
    assert db["jobs"].find_one({"_id": "j1"})["status"] == "FAILED"


def test_purge_endpoint_detaches_functions_still_held_by_other_endpoints(client, collections, db):
    collections.endpoints.insert_one({"_id": "n0", "endpoint_id": "n0", "status": "stopped"})
    collections.functions.insert_one({"_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["n0", "n1"]})

    response = client.delete("/endpoints/n0/purge")

    assert response.status_code == 200
    body = response.json()
    assert body["functions_marked_deleted"] == 0
    assert body["functions_detached"] == 1
    doc = collections.functions.find_one({"_id": "add:1"})
    assert doc.get("deleted_at") is None
    assert doc["endpoint_id"] == ["n1"]
