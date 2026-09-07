from datetime import datetime, timedelta, timezone

import mongomock
from option import Err, Ok

from axo_shared.errors import AxoError
from axo_shared.protocol import CommandResult

from axo_vem.infrastructure.transport.zmq_command import endpoint_liveness_worker as worker_module
from axo_vem.infrastructure.transport.zmq_command.endpoint_liveness_worker import EndpointLivenessWorker


class _FakeEventPublisher:
    def __init__(self):
        self.appended = []

    def append_to_stream(self, stream_name, event_type, data):
        self.appended.append((stream_name, event_type, data))


def _iso(dt):
    return dt.isoformat()


def _worker(endpoints, stale_after_seconds=90.0):
    publisher = _FakeEventPublisher()
    return EndpointLivenessWorker(endpoints, publisher, stale_after_seconds, tick_seconds=1.0), publisher


def _collection():
    return mongomock.MongoClient()["test"]["endpoints"]


def test_fresh_running_endpoint_is_skipped_without_pinging(monkeypatch):
    endpoints = _collection()
    now = datetime.now(timezone.utc)
    endpoints.insert_one({
        "_id": "n0", "status": "running", "router_bind": "tcp://0.0.0.0:5555", "created_at": _iso(now),
    })
    worker, publisher = _worker(endpoints, stale_after_seconds=90.0)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("send_command should never be called for a fresh endpoint")

    monkeypatch.setattr(worker_module, "send_command", fail_if_called)

    worker.tick()

    assert publisher.appended == []


def test_stale_running_endpoint_unreachable_ping_appends_unreachable_event(monkeypatch):
    endpoints = _collection()
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=200)
    endpoints.insert_one({
        "_id": "n0", "status": "running", "router_bind": "tcp://0.0.0.0:5555", "created_at": _iso(stale_time),
    })
    worker, publisher = _worker(endpoints, stale_after_seconds=90.0)
    monkeypatch.setattr(
        worker_module, "send_command",
        lambda rpc_uri, command, timeout: Err(AxoError("timed out")),
    )

    worker.tick()

    assert len(publisher.appended) == 1
    stream_name, event_type, data = publisher.appended[0]
    assert stream_name == "endpoints-n0"
    assert event_type == "EndpointUnreachable"
    assert data["endpoint_id"] == "n0"
    assert data["last_seen_at"] == _iso(stale_time)


def test_stale_running_endpoint_reachable_ping_appends_nothing(monkeypatch):
    endpoints = _collection()
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=200)
    endpoints.insert_one({
        "_id": "n0", "status": "running", "router_bind": "tcp://0.0.0.0:5555", "created_at": _iso(stale_time),
    })
    worker, publisher = _worker(endpoints, stale_after_seconds=90.0)
    monkeypatch.setattr(
        worker_module, "send_command",
        lambda rpc_uri, command, timeout: Ok(CommandResult(ok=True)),
    )

    worker.tick()

    assert publisher.appended == []


def test_unreachable_endpoint_reachable_ping_appends_recovered_event(monkeypatch):
    endpoints = _collection()
    endpoints.insert_one({
        "_id": "n0", "status": "unreachable", "router_bind": "tcp://0.0.0.0:5555",
        "created_at": _iso(datetime.now(timezone.utc)),
    })
    worker, publisher = _worker(endpoints)
    monkeypatch.setattr(
        worker_module, "send_command",
        lambda rpc_uri, command, timeout: Ok(CommandResult(ok=True)),
    )

    worker.tick()

    assert len(publisher.appended) == 1
    stream_name, event_type, data = publisher.appended[0]
    assert stream_name == "endpoints-n0"
    assert event_type == "EndpointRecovered"
    assert data["endpoint_id"] == "n0"


def test_unreachable_endpoint_still_unreachable_appends_nothing(monkeypatch):
    endpoints = _collection()
    endpoints.insert_one({
        "_id": "n0", "status": "unreachable", "router_bind": "tcp://0.0.0.0:5555",
        "created_at": _iso(datetime.now(timezone.utc)),
    })
    worker, publisher = _worker(endpoints)
    monkeypatch.setattr(
        worker_module, "send_command",
        lambda rpc_uri, command, timeout: Err(AxoError("timed out")),
    )

    worker.tick()

    assert publisher.appended == []


def test_endpoint_with_no_router_bind_is_skipped_without_crashing(monkeypatch):
    endpoints = _collection()
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=200)
    endpoints.insert_one({"_id": "n0", "status": "running", "created_at": _iso(stale_time)})
    worker, publisher = _worker(endpoints, stale_after_seconds=90.0)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("send_command should never be called without a router_bind")

    monkeypatch.setattr(worker_module, "send_command", fail_if_called)

    worker.tick()  # must not raise

    assert publisher.appended == []


def test_stop_ends_run_forever_after_one_tick(monkeypatch):
    endpoints = _collection()
    worker, _ = _worker(endpoints)
    monkeypatch.setattr(worker, "tick", lambda: worker.stop())
    monkeypatch.setattr(worker_module.time, "sleep", lambda _seconds: None)

    worker.run_forever()  # must return, not hang
