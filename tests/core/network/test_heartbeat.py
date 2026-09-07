import dataclasses

import pytest

from axo_endpoint.core.network import HeartbeatPublisher, HeartbeatSubscriber, PeerInfo


def test_peer_info_equality_and_defaults():
    a = PeerInfo(peer_id="p1", service_name="axo-endpoint", rpc_uri="tcp://h:1")
    b = PeerInfo(peer_id="p1", service_name="axo-endpoint", rpc_uri="tcp://h:1")
    assert a == b
    assert a.metrics == {}
    assert a.last_seen == 0.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.last_seen = 1.0


def test_heartbeat_publisher_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        HeartbeatPublisher()


def test_heartbeat_subscriber_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        HeartbeatSubscriber()


class _DictHeartbeatSubscriber(HeartbeatSubscriber):
    """Trivial in-memory implementation used only to exercise the contract."""

    def __init__(self):
        self._peers = {}

    def on_heartbeat(self, info: PeerInfo) -> None:
        self._peers[info.peer_id] = info

    def evict_stale(self, ttl_seconds: float, now: float):
        stale_ids = [
            pid for pid, info in self._peers.items() if now - info.last_seen > ttl_seconds
        ]
        for pid in stale_ids:
            self._peers.pop(pid, None)
        return stale_ids

    def get_peer(self, peer_id: str):
        return self._peers.get(peer_id)

    def list_peers(self):
        return list(self._peers.values())


def test_on_heartbeat_upserts_peer():
    subscriber = _DictHeartbeatSubscriber()
    info = PeerInfo(peer_id="p1", service_name="axo-endpoint", rpc_uri="tcp://h:1", last_seen=100.0)
    subscriber.on_heartbeat(info)
    assert subscriber.get_peer("p1") == info

    updated = dataclasses.replace(info, last_seen=200.0)
    subscriber.on_heartbeat(updated)
    assert subscriber.get_peer("p1") == updated


def test_evict_stale_removes_only_peers_past_ttl():
    subscriber = _DictHeartbeatSubscriber()
    fresh = PeerInfo(peer_id="fresh", service_name="svc", rpc_uri="tcp://h:1", last_seen=95.0)
    stale = PeerInfo(peer_id="stale", service_name="svc", rpc_uri="tcp://h:2", last_seen=50.0)
    subscriber.on_heartbeat(fresh)
    subscriber.on_heartbeat(stale)

    evicted = subscriber.evict_stale(ttl_seconds=30.0, now=100.0)

    assert evicted == ["stale"]
    assert subscriber.get_peer("stale") is None
    assert subscriber.get_peer("fresh") == fresh
    assert subscriber.list_peers() == [fresh]
