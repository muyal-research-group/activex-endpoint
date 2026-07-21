from fastapi.testclient import TestClient
from option import Err, Ok

from axo_shared.container.errors import ContainerSpawnError
from axo_shared.container.handle import SpawnedContainerHandle

from axo_vem.application.nodes.launch_endpoint_node import LaunchEndpointNodeUseCase
from axo_vem.infrastructure.transport.api.app import create_app

from .conftest import _fake_current_user


class _FakeSpawner:
    def __init__(self, result=None):
        self._result = result

    def spawn(self, **kwargs):
        if self._result is not None:
            return self._result
        return Ok(SpawnedContainerHandle(name=kwargs["name"], mode=kwargs["mode"], container_id="c1"))


def _deploy_client(collections, activity_repository, spawn_result=None):
    use_case = LaunchEndpointNodeUseCase(
        spawner=_FakeSpawner(result=spawn_result), image="axo-endpoint:local", network="axo-net",
    )
    app = create_app(
        collections=collections,
        activity_repository=activity_repository,
        launch_endpoint_node_use_case=use_case,
        node_api_uri="tcp://axo-vem:6000",
        current_user_dependency=_fake_current_user,
    )
    return TestClient(app)


def test_deploy_endpoint_returns_launched_endpoint(collections, activity_repository):
    client = _deploy_client(collections, activity_repository)

    response = client.post("/endpoints", json={"virtual_environment_id": "ve1"})

    assert response.status_code == 201
    body = response.json()
    assert body["endpoint_id"].startswith("axo-endpoint-")
    assert body["router_bind"] == "tcp://0.0.0.0:5555"


def test_deploy_endpoint_returns_502_on_spawn_failure(collections, activity_repository):
    client = _deploy_client(collections, activity_repository, spawn_result=Err(ContainerSpawnError("boom")))

    response = client.post("/endpoints", json={})

    assert response.status_code == 502


def test_get_deployment_defaults_returns_env_var_map(collections, activity_repository):
    client = _deploy_client(collections, activity_repository)

    response = client.get("/endpoints/deployment-defaults")

    assert response.status_code == 200
    body = response.json()
    assert body["AXO_ENDPOINT_QUEUE_WORKERS"] == "8"
    assert "AXO_ENDPOINT_ID" in body


def test_deploy_routes_absent_when_use_case_not_configured(collections, activity_repository):
    app = create_app(
        collections=collections, activity_repository=activity_repository, current_user_dependency=_fake_current_user,
    )
    client = TestClient(app)

    # GET /endpoints already exists (list_endpoints), so POST /endpoints
    # without the deploy route registered is "method not allowed", not
    # "no matching route at all".
    response = client.post("/endpoints", json={})
    assert response.status_code == 405

    # Falls through to GET /endpoints/{endpoint_id} instead (still 404, but
    # from that handler's own "endpoint not found" -- deployment-defaults
    # is treated as an endpoint_id path param when the dedicated route
    # above it isn't registered).
    response = client.get("/endpoints/deployment-defaults")
    assert response.status_code == 404
    assert response.json()["detail"] == "endpoint not found"
