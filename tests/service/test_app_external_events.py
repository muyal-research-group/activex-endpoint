import threading
import time

import cloudpickle
import zmq

from axo_shared import wire
from axo_shared.events import envelope, models
from axo_shared.protocol import Command
from axo_endpoint.config import Config
from axo_endpoint.service.app import App


def _send_command(dealer, command: Command):
    dealer.send_multipart(wire.encode_command(command))
    frames = dealer.recv_multipart()
    return wire.decode_command_result(frames).unwrap()


def test_app_forwards_lifecycle_events_when_api_uri_is_configured(tmp_path, clean_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_ROUTER_BIND", f"ipc://{tmp_path}/router.sock")
    monkeypatch.setenv("AXO_ENDPOINT_PUB_BIND", f"ipc://{tmp_path}/pub.sock")
    monkeypatch.setenv("AXO_ENDPOINT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setenv("AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS", "0.2")
    api_address = f"ipc://{tmp_path}/api.sock"
    monkeypatch.setenv("AXO_ENDPOINT_API_URI", api_address)

    stub_router = zmq.Context.instance().socket(zmq.ROUTER)
    stub_router.setsockopt(zmq.RCVTIMEO, 200)
    stub_router.bind(api_address)

    received = []
    stop_collecting = threading.Event()

    def _collect():
        while not stop_collecting.is_set():
            try:
                frames = stub_router.recv_multipart()
            except zmq.Again:
                continue
            command = wire.decode_command(frames[1:]).unwrap()
            event_type, endpoint_id, data = envelope.decode_event(command).unwrap()
            received.append((event_type, endpoint_id, data))

    collector_thread = threading.Thread(target=_collect, daemon=True)
    collector_thread.start()

    app = App(Config())
    app_thread = threading.Thread(target=app.run, daemon=True)
    app_thread.start()

    dealer = zmq.Context.instance().socket(zmq.DEALER)
    dealer.setsockopt(zmq.RCVTIMEO, 2000)
    dealer.connect(app.config.AXO_ENDPOINT_ROUTER_BIND)

    try:
        register_result = _send_command(
            dealer,
            Command(
                operation=wire.FUNCTION_REGISTER,
                content_type="application/octet-stream",
                envelope={"function_id": "add", "name": "add"},
                payload=cloudpickle.dumps(lambda params, ctx: params["a"] + params["b"]),
            ),
        )
        assert register_result.ok is True

        submit_result = _send_command(
            dealer,
            Command(
                operation=wire.JOB_SUBMIT,
                content_type="application/json",
                envelope={"function_id": "add", "function_name": "add", "function_version": 1, "params": {"a": 2, "b": 3}},
            ),
        )
        assert submit_result.ok is True

        deadline = time.time() + 10.0
        seen_types = set()
        needed = {
            models.ENDPOINT_STARTED,
            models.ENDPOINT_METRICS_REPORTED,
            models.FUNCTION_REGISTERED,
            models.FUNCTION_DEPLOYED,
            models.JOB_QUEUED,
            models.JOB_STARTED,
            models.JOB_COMPLETED,
            models.FUNCTION_ACTIVATED,
            models.FUNCTION_DEACTIVATED,
        }
        while time.time() < deadline and not needed.issubset(seen_types):
            seen_types = {t for t, _, _ in received}
            time.sleep(0.1)

        assert needed.issubset(seen_types), f"missing event types: {needed - seen_types}, got: {seen_types}"

        for event_type, endpoint_id, _data in received:
            assert endpoint_id == app.config.AXO_ENDPOINT_ID
    finally:
        stop_collecting.set()
        collector_thread.join(timeout=2.0)
        dealer.close()
        app.stop()
        app_thread.join(timeout=5.0)
        stub_router.close()


def test_app_does_not_construct_external_publisher_when_api_uri_unset(tmp_path, clean_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_ROUTER_BIND", f"ipc://{tmp_path}/router.sock")
    monkeypatch.setenv("AXO_ENDPOINT_PUB_BIND", f"ipc://{tmp_path}/pub.sock")
    monkeypatch.setenv("AXO_ENDPOINT_SCRATCH_ROOT", str(tmp_path / "scratch"))

    app = App(Config())

    assert app.external_publisher is None
    assert app.external_bridge is None
