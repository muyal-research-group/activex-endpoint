from types import SimpleNamespace

import docker.errors
import pytest

from axo_shared.container.errors import ContainerSpawnError
from axo_shared.container.handle import ContainerStats, MountSpec, SpawnedContainerHandle
from axo_shared.container.spawner import ContainerSpawner


class _FakeContainer:
    id = "container-123"
    name = "my-container"

    def stop(self, timeout=5):
        pass

    def remove(self):
        pass


class _FakeService:
    id = "service-123"
    name = "my-service"

    def remove(self):
        pass


@pytest.fixture
def spawner():
    return ContainerSpawner()


def test_spawn_docker_mode_creates_a_container(spawner, monkeypatch):
    ran_kwargs = {}

    def fake_run(**kwargs):
        ran_kwargs.update(kwargs)
        return _FakeContainer()

    fake_client = SimpleNamespace(containers=SimpleNamespace(run=fake_run))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.spawn(
        mode="docker", image="my-image:latest", name="my-container",
        env={"FOO": "bar"}, network="my-net",
        mounts=[MountSpec(source="/host/path", target="/container/path", mode="ro")],
    )

    assert result.is_ok
    handle = result.unwrap()
    assert handle == SpawnedContainerHandle(name="my-container", mode="docker", container_id="container-123")
    assert ran_kwargs["image"] == "my-image:latest"
    assert ran_kwargs["environment"] == {"FOO": "bar"}
    assert ran_kwargs["network"] == "my-net"
    assert ran_kwargs["volumes"] == {"/host/path": {"bind": "/container/path", "mode": "ro"}}
    assert ran_kwargs["detach"] is True


def test_spawn_docker_mode_passes_mem_and_cpu_limits(spawner, monkeypatch):
    ran_kwargs = {}

    def fake_run(**kwargs):
        ran_kwargs.update(kwargs)
        return _FakeContainer()

    fake_client = SimpleNamespace(containers=SimpleNamespace(run=fake_run))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    spawner.spawn(
        mode="docker", image="my-image:latest", name="my-container", env={},
        mem_limit_bytes=1073741824, nano_cpus=1_000_000_000,
    )

    assert ran_kwargs["mem_limit"] == 1073741824
    assert ran_kwargs["nano_cpus"] == 1_000_000_000


def test_spawn_docker_mode_omits_limits_when_unset(spawner, monkeypatch):
    ran_kwargs = {}

    def fake_run(**kwargs):
        ran_kwargs.update(kwargs)
        return _FakeContainer()

    fake_client = SimpleNamespace(containers=SimpleNamespace(run=fake_run))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    spawner.spawn(mode="docker", image="my-image:latest", name="my-container", env={})

    assert ran_kwargs["mem_limit"] is None
    assert ran_kwargs["nano_cpus"] is None


def test_spawn_swarm_mode_passes_resources_when_limits_set(spawner, monkeypatch):
    create_kwargs = {}

    def fake_create(**kwargs):
        create_kwargs.update(kwargs)
        return _FakeService()

    fake_client = SimpleNamespace(services=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    spawner.spawn(
        mode="swarm", image="my-image:latest", name="my-service", env={},
        mem_limit_bytes=1073741824, nano_cpus=1_000_000_000,
    )

    resources = create_kwargs["resources"]
    assert resources is not None
    assert resources["Limits"]["MemoryBytes"] == 1073741824
    assert resources["Limits"]["NanoCPUs"] == 1_000_000_000


def test_spawn_swarm_mode_omits_resources_when_limits_unset(spawner, monkeypatch):
    create_kwargs = {}

    def fake_create(**kwargs):
        create_kwargs.update(kwargs)
        return _FakeService()

    fake_client = SimpleNamespace(services=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    spawner.spawn(mode="swarm", image="my-image:latest", name="my-service", env={})

    assert create_kwargs["resources"] is None


def test_spawn_swarm_mode_creates_a_service(spawner, monkeypatch):
    create_kwargs = {}

    def fake_create(**kwargs):
        create_kwargs.update(kwargs)
        return _FakeService()

    fake_client = SimpleNamespace(services=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.spawn(
        mode="swarm", image="my-image:latest", name="my-service", env={"FOO": "bar"}, network="my-net",
        mounts=[MountSpec(source="/host/path", target="/container/path")],
    )

    assert result.is_ok
    handle = result.unwrap()
    assert handle == SpawnedContainerHandle(name="my-service", mode="swarm", service_id="service-123")
    assert create_kwargs["env"] == ["FOO=bar"]
    assert create_kwargs["networks"] == ["my-net"]
    assert create_kwargs["mounts"] == ["/host/path:/container/path:rw"]


def test_spawn_returns_err_on_docker_exception(spawner, monkeypatch):
    def fake_run(**kwargs):
        raise docker.errors.DockerException("boom")

    fake_client = SimpleNamespace(containers=SimpleNamespace(run=fake_run))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.spawn(mode="docker", image="x", name="x", env={})

    assert result.is_err
    assert isinstance(result.unwrap_err(), ContainerSpawnError)


def test_stop_docker_mode_stops_and_removes(spawner, monkeypatch):
    calls = []
    container = _FakeContainer()
    container.stop = lambda timeout=5: calls.append(("stop", timeout))
    container.remove = lambda: calls.append(("remove",))
    fake_client = SimpleNamespace(containers=SimpleNamespace(get=lambda cid: container))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.stop(SpawnedContainerHandle(name="x", mode="docker", container_id="container-123"))

    assert result.is_ok
    assert calls == [("stop", 5), ("remove",)]


def test_stop_swarm_mode_removes_service(spawner, monkeypatch):
    calls = []
    service = _FakeService()
    service.remove = lambda: calls.append("removed")
    fake_client = SimpleNamespace(services=SimpleNamespace(get=lambda sid: service))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.stop(SpawnedContainerHandle(name="x", mode="swarm", service_id="service-123"))

    assert result.is_ok
    assert calls == ["removed"]


def test_stop_is_idempotent_when_already_gone(spawner, monkeypatch):
    def fake_get(cid):
        raise docker.errors.NotFound("not found")

    fake_client = SimpleNamespace(containers=SimpleNamespace(get=fake_get))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.stop(SpawnedContainerHandle(name="x", mode="docker", container_id="container-123"))

    assert result.is_ok


def test_restart_docker_mode_restarts_same_container(spawner, monkeypatch):
    calls = []
    container = _FakeContainer()
    container.restart = lambda timeout=10: calls.append(("restart", timeout))
    fake_client = SimpleNamespace(containers=SimpleNamespace(get=lambda cid: container))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.restart(SpawnedContainerHandle(name="x", mode="docker", container_id="container-123"))

    assert result.is_ok
    assert calls == [("restart", 10)]


def test_restart_swarm_mode_force_updates_service(spawner, monkeypatch):
    calls = []
    service = _FakeService()
    service.force_update = lambda: calls.append("force_updated")
    fake_client = SimpleNamespace(services=SimpleNamespace(get=lambda sid: service))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.restart(SpawnedContainerHandle(name="x", mode="swarm", service_id="service-123"))

    assert result.is_ok
    assert calls == ["force_updated"]


def test_restart_returns_err_when_not_found(spawner, monkeypatch):
    def fake_get(cid):
        raise docker.errors.NotFound("not found")

    fake_client = SimpleNamespace(containers=SimpleNamespace(get=fake_get))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.restart(SpawnedContainerHandle(name="x", mode="docker", container_id="container-123"))

    assert result.is_err


def test_get_returns_none_when_not_found(spawner, monkeypatch):
    def fake_get(cid):
        raise docker.errors.NotFound("not found")

    fake_client = SimpleNamespace(containers=SimpleNamespace(get=fake_get))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    assert spawner.get("docker", "missing") is None


def test_get_returns_handle_when_found(spawner, monkeypatch):
    fake_client = SimpleNamespace(containers=SimpleNamespace(get=lambda cid: _FakeContainer()))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    handle = spawner.get("docker", "container-123")
    assert handle == SpawnedContainerHandle(name="my-container", mode="docker", container_id="container-123")


def test_ensure_image_returns_ok_when_present(spawner, monkeypatch):
    fake_client = SimpleNamespace(images=SimpleNamespace(get=lambda image: object()))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.ensure_image("my-image:latest")
    assert result.is_ok
    assert result.unwrap() == "my-image:latest"


def test_ensure_image_returns_err_when_missing(spawner, monkeypatch):
    def fake_get(image):
        raise docker.errors.ImageNotFound("not found")

    fake_client = SimpleNamespace(images=SimpleNamespace(get=fake_get))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.ensure_image("missing-image")
    assert result.is_err


def test_build_image_consumes_log_stream_and_returns_tag(spawner, monkeypatch):
    build_kwargs = {}

    def fake_build(**kwargs):
        build_kwargs.update(kwargs)
        return object(), iter([{"stream": "step 1"}, {"stream": "step 2"}])

    fake_client = SimpleNamespace(images=SimpleNamespace(build=fake_build))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.build_image(
        context_path="/repo", dockerfile="/repo/Dockerfile", tag="my-image:py3.10",
        buildargs={"PYTHON_VERSION": "3.10"},
    )

    assert result.is_ok
    assert result.unwrap() == "my-image:py3.10"
    assert build_kwargs["path"] == "/repo"
    assert build_kwargs["tag"] == "my-image:py3.10"
    assert build_kwargs["buildargs"] == {"PYTHON_VERSION": "3.10"}


_RAW_STATS = {
    "cpu_stats": {
        "cpu_usage": {"total_usage": 2_000_000_000},
        "system_cpu_usage": 10_000_000_000,
        "online_cpus": 4,
    },
    "precpu_stats": {
        "cpu_usage": {"total_usage": 1_000_000_000},
        "system_cpu_usage": 9_000_000_000,
    },
    "memory_stats": {
        "usage": 500_000_000,
        "limit": 2_000_000_000,
        "stats": {"cache": 100_000_000},
    },
    "networks": {
        "eth0": {"rx_bytes": 1000, "tx_bytes": 2000},
        "eth1": {"rx_bytes": 500, "tx_bytes": 600},
    },
}


def test_stats_computes_cpu_percent_memory_and_network_totals(spawner, monkeypatch):
    container = _FakeContainer()
    container.stats = lambda stream=False: _RAW_STATS
    fake_client = SimpleNamespace(containers=SimpleNamespace(get=lambda cid: container))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.stats(SpawnedContainerHandle(name="x", mode="docker", container_id="container-123"))

    assert result.is_ok
    assert result.unwrap() == ContainerStats(
        cpu_percent=400.0, memory_usage=400_000_000, memory_limit=2_000_000_000,
        network_rx=1500, network_tx=2600,
    )


def test_stats_zero_cpu_delta_reports_zero_percent(spawner, monkeypatch):
    raw = {
        **_RAW_STATS,
        "cpu_stats": {**_RAW_STATS["cpu_stats"], "cpu_usage": {"total_usage": 1_000_000_000}},
    }
    container = _FakeContainer()
    container.stats = lambda stream=False: raw
    fake_client = SimpleNamespace(containers=SimpleNamespace(get=lambda cid: container))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.stats(SpawnedContainerHandle(name="x", mode="docker", container_id="container-123"))

    assert result.is_ok
    assert result.unwrap().cpu_percent == 0.0


def test_stats_returns_err_when_container_not_found(spawner, monkeypatch):
    def fake_get(cid):
        raise docker.errors.NotFound("not found")

    fake_client = SimpleNamespace(containers=SimpleNamespace(get=fake_get))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.stats(SpawnedContainerHandle(name="x", mode="docker", container_id="container-123"))
    assert result.is_err
    assert isinstance(result.unwrap_err(), ContainerSpawnError)


def test_stats_returns_err_for_swarm_handles(spawner):
    result = spawner.stats(SpawnedContainerHandle(name="x", mode="swarm", service_id="service-123"))
    assert result.is_err


def test_build_image_returns_err_on_build_error(spawner, monkeypatch):
    def fake_build(**kwargs):
        raise docker.errors.BuildError("boom", build_log=[])

    fake_client = SimpleNamespace(images=SimpleNamespace(build=fake_build))
    monkeypatch.setattr(spawner, "_docker", lambda: fake_client)

    result = spawner.build_image(context_path="/repo", dockerfile="/repo/Dockerfile", tag="x")
    assert result.is_err
