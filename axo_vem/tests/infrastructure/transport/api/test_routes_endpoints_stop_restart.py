from fastapi.testclient import TestClient
from option import Ok

from axo_shared.container.handle import SpawnedContainerHandle

from axo_vem.application.nodes.launch_endpoint_node import LaunchEndpointNodeUseCase
from axo_vem.application.nodes.restart_endpoint_node import RestartEndpointNodeUseCase
from axo_vem.application.nodes.stop_endpoint_node import StopEndpointNodeUseCase
from axo_vem.infrastructure.transport.api.app import create_app

from .conftest import _fake_current_user


class _FakeSpawner:
    def __init__(self, handle=None):
        self._handle = handle
        self.stop_calls = []
        self.restart_calls = []

    def get(self, mode, container_or_service_id):
        return self._handle

    def stop(self, handle, timeout=5):
        self.stop_calls.append((handle, timeout))
        return Ok(None)

    def restart(self, handle, timeout=10):
        self.restart_calls.append((handle, timeout))
        return Ok(None)


def _client(collections, activity_repository, spawner):
    app = create_app(
        collections=collections,
        activity_repository=activity_repository,
        # unused by stop/restart directly, but the gate that registers this
        # whole Docker-management route group also covers stop/restart.
        launch_endpoint_node_use_case=LaunchEndpointNodeUseCase(
            spawner=spawner, image="axo-endpoint:local", network="axo-net",
        ),
        node_api_uri="tcp://axo-vem:6000",
        stop_endpoint_node_use_case=StopEndpointNodeUseCase(spawner=spawner, mode="docker"),
        restart_endpoint_node_use_case=RestartEndpointNodeUseCase(spawner=spawner, mode="docker"),
        current_user_dependency=_fake_current_user,
    )
    return TestClient(app)


def test_stop_endpoint_stops_managed_container(collections, activity_repository):
    handle = SpawnedContainerHandle(name="axo-endpoint-1", mode="docker", container_id="c1")
    spawner = _FakeSpawner(handle=handle)
    client = _client(collections, activity_repository, spawner)

    response = client.post("/endpoints/axo-endpoint-1/stop")

    assert response.status_code == 200
    assert response.json() == {"endpoint_id": "axo-endpoint-1", "status": "stopped"}
    assert spawner.stop_calls == [(handle, 10)]


def test_stop_endpoint_returns_404_when_not_managed_by_this_api(collections, activity_repository):
    spawner = _FakeSpawner(handle=None)
    client = _client(collections, activity_repository, spawner)

    response = client.post("/endpoints/some-compose-node/stop")

    assert response.status_code == 404
    assert "not managed by this API" in response.json()["detail"]


def test_restart_endpoint_restarts_managed_container(collections, activity_repository):
    handle = SpawnedContainerHandle(name="axo-endpoint-1", mode="docker", container_id="c1")
    spawner = _FakeSpawner(handle=handle)
    client = _client(collections, activity_repository, spawner)

    response = client.post("/endpoints/axo-endpoint-1/restart")

    assert response.status_code == 200
    assert response.json() == {"endpoint_id": "axo-endpoint-1", "status": "restarted"}
    assert spawner.restart_calls == [(handle, 10)]


def test_restart_endpoint_returns_404_when_not_managed_by_this_api(collections, activity_repository):
    spawner = _FakeSpawner(handle=None)
    client = _client(collections, activity_repository, spawner)

    response = client.post("/endpoints/some-compose-node/restart")

    assert response.status_code == 404
