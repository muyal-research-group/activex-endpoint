import mongomock
from option import Err, Ok

from axo_shared.container.errors import ContainerSpawnError
from axo_shared.container.handle import ContainerStats, SpawnedContainerHandle

from axo_vem.infrastructure.container.endpoint_stats_poller import EndpointStatsPoller


class _FakeBroadcaster:
    def __init__(self):
        self.broadcast_calls = []

    def broadcast(self, topic, message):
        self.broadcast_calls.append((topic, message))


class _FakeSpawner:
    def __init__(self, handles=None, stats_by_container_id=None, stats_errors=None):
        self._handles = handles or {}
        self._stats_by_container_id = stats_by_container_id or {}
        self._stats_errors = stats_errors or set()

    def get(self, mode, endpoint_id):
        return self._handles.get(endpoint_id)

    def stats(self, handle):
        if handle.container_id in self._stats_errors:
            return Err(ContainerSpawnError("boom"))
        return Ok(self._stats_by_container_id[handle.container_id])


def _endpoints_collection():
    return mongomock.MongoClient()["test"]["endpoints"]


def test_tick_broadcasts_available_stats_for_a_managed_endpoint():
    endpoints = _endpoints_collection()
    endpoints.insert_one({"_id": "n0"})

    handle = SpawnedContainerHandle(name="n0", mode="docker", container_id="c0")
    stats = ContainerStats(cpu_percent=12.5, memory_usage=100, memory_limit=1000, network_rx=10, network_tx=20)
    spawner = _FakeSpawner(handles={"n0": handle}, stats_by_container_id={"c0": stats})
    broadcaster = _FakeBroadcaster()

    poller = EndpointStatsPoller(endpoints=endpoints, spawner=spawner, mode="docker", broadcaster=broadcaster)
    poller.tick()

    expected_message = {
        "endpoint_id": "n0", "available": True,
        "cpu_percent": 12.5, "memory_usage": 100, "memory_limit": 1000,
        "network_rx": 10, "network_tx": 20,
    }
    assert broadcaster.broadcast_calls == [
        ("endpoints", expected_message),
        ("endpoints:n0", expected_message),
    ]


def test_tick_reports_unavailable_for_an_unmanaged_endpoint():
    endpoints = _endpoints_collection()
    endpoints.insert_one({"_id": "compose-node"})

    spawner = _FakeSpawner(handles={})  # get() returns None -- not launched by this API
    broadcaster = _FakeBroadcaster()

    poller = EndpointStatsPoller(endpoints=endpoints, spawner=spawner, mode="docker", broadcaster=broadcaster)
    poller.tick()

    expected_message = {"endpoint_id": "compose-node", "available": False}
    assert broadcaster.broadcast_calls == [
        ("endpoints", expected_message),
        ("endpoints:compose-node", expected_message),
    ]


def test_tick_reports_unavailable_when_stats_call_fails():
    endpoints = _endpoints_collection()
    endpoints.insert_one({"_id": "n0"})

    handle = SpawnedContainerHandle(name="n0", mode="docker", container_id="c0")
    spawner = _FakeSpawner(handles={"n0": handle}, stats_errors={"c0"})
    broadcaster = _FakeBroadcaster()

    poller = EndpointStatsPoller(endpoints=endpoints, spawner=spawner, mode="docker", broadcaster=broadcaster)
    poller.tick()

    assert broadcaster.broadcast_calls == [
        ("endpoints", {"endpoint_id": "n0", "available": False}),
        ("endpoints:n0", {"endpoint_id": "n0", "available": False}),
    ]


def test_tick_covers_every_endpoint_independently():
    endpoints = _endpoints_collection()
    endpoints.insert_one({"_id": "n0"})
    endpoints.insert_one({"_id": "n1"})

    handle0 = SpawnedContainerHandle(name="n0", mode="docker", container_id="c0")
    stats0 = ContainerStats(cpu_percent=1.0, memory_usage=1, memory_limit=10, network_rx=1, network_tx=1)
    spawner = _FakeSpawner(handles={"n0": handle0}, stats_by_container_id={"c0": stats0})
    broadcaster = _FakeBroadcaster()

    poller = EndpointStatsPoller(endpoints=endpoints, spawner=spawner, mode="docker", broadcaster=broadcaster)
    poller.tick()

    topics = [call[0] for call in broadcaster.broadcast_calls]
    assert topics == ["endpoints", "endpoints:n0", "endpoints", "endpoints:n1"]


def test_stop_ends_run_forever_after_one_tick(monkeypatch):
    endpoints = _endpoints_collection()
    spawner = _FakeSpawner()
    broadcaster = _FakeBroadcaster()
    poller = EndpointStatsPoller(
        endpoints=endpoints, spawner=spawner, mode="docker", broadcaster=broadcaster, interval_seconds=0.0,
    )

    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        poller.stop()

    monkeypatch.setattr("axo_vem.infrastructure.container.endpoint_stats_poller.time.sleep", fake_sleep)
    poller.run_forever()

    assert sleep_calls == [0.0]
