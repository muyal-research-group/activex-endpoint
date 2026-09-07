import threading
import time

from axo_endpoint.core.network import PeerInfo
from axo_endpoint.service.transport.heartbeat_zmq import (
    ZmqHeartbeatPublisher,
    ZmqHeartbeatSubscriber,
    run_heartbeat_gc,
)


def test_publish_then_subscribe_delivers_peer_info(tmp_path):
    address = f"ipc://{tmp_path}/heartbeat.sock"
    publisher = ZmqHeartbeatPublisher(bind_address=address)
    subscriber = ZmqHeartbeatSubscriber(connect_addresses=[address], now_fn=lambda: 100.0)
    subscriber.start()

    info = PeerInfo(peer_id="p1", service_name="axo-endpoint", rpc_uri="tcp://h:1", metrics={"load": 0.5})

    # PUB/SUB has a well-known "slow joiner" delay -- the subscription filter
    # may not have propagated to the publisher yet right after connect(), so
    # retry-publishing until it's received (bounded) is the standard fix.
    deadline = time.time() + 5.0
    while time.time() < deadline and subscriber.get_peer("p1") is None:
        publisher.publish(info)
        time.sleep(0.05)

    received = subscriber.get_peer("p1")
    assert received is not None
    assert received.peer_id == "p1"
    assert received.service_name == "axo-endpoint"
    assert received.rpc_uri == "tcp://h:1"
    assert received.metrics == {"load": 0.5}
    assert received.last_seen == 100.0  # stamped by the subscriber's now_fn, not the wire

    subscriber.stop()
    publisher.close()


def test_evict_stale_wiring_delegates_to_the_already_tested_logic():
    subscriber = ZmqHeartbeatSubscriber(connect_addresses=[])
    fresh = PeerInfo(peer_id="fresh", service_name="svc", rpc_uri="tcp://h:1", last_seen=95.0)
    stale = PeerInfo(peer_id="stale", service_name="svc", rpc_uri="tcp://h:2", last_seen=50.0)
    subscriber.on_heartbeat(fresh)
    subscriber.on_heartbeat(stale)

    evicted = subscriber.evict_stale(ttl_seconds=30.0, now=100.0)

    assert evicted == ["stale"]
    assert subscriber.get_peer("stale") is None
    assert subscriber.get_peer("fresh") == fresh
    assert subscriber.list_peers() == [fresh]


def test_run_heartbeat_gc_calls_evict_stale_on_the_expected_cadence():
    subscriber = ZmqHeartbeatSubscriber(connect_addresses=[])
    subscriber.on_heartbeat(PeerInfo(peer_id="stale", service_name="svc", rpc_uri="tcp://h:1", last_seen=0.0))

    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_heartbeat_gc, args=(subscriber, 0.0, 0.05, stop_event), daemon=True
    )
    thread.start()

    deadline = time.time() + 2.0
    while time.time() < deadline and subscriber.get_peer("stale") is not None:
        time.sleep(0.01)

    assert subscriber.get_peer("stale") is None

    stop_event.set()
    thread.join(timeout=2.0)
