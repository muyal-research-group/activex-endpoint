import threading
import time

import cloudpickle
import zmq

from axo_shared.protocol import Command
from axo_endpoint.service.app import App
from axo_endpoint.config import Config
from axo_shared import wire


def _send_command(dealer, command: Command):
    dealer.send_multipart(wire.encode_command(command))
    frames = dealer.recv_multipart()
    return wire.decode_command_result(frames).unwrap()


def _poll_until_terminal(dealer, job_id, timeout=10.0):
    """Drains whatever arrives (a genuine poll reply, or an unsolicited
    push -- both carry equally valid news about this job_id) until a
    terminal status is observed."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        dealer.send_multipart(
            wire.encode_command(
                Command(operation=wire.JOB_RESULT, content_type="application/json", envelope={"job_id": job_id})
            )
        )
        try:
            frames = dealer.recv_multipart()
        except zmq.Again:
            continue
        result = wire.decode_command_result(frames).unwrap()
        if result.metadata.get("job_id") == job_id and result.metadata.get("status") in ("COMPLETED", "FAILED"):
            return result
        time.sleep(0.1)
    raise TimeoutError(f"job {job_id} did not reach a terminal status in time")


def test_register_submit_and_poll_result_end_to_end(tmp_path, clean_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_ROUTER_BIND", f"ipc://{tmp_path}/router.sock")
    monkeypatch.setenv("AXO_ENDPOINT_PUB_BIND", f"ipc://{tmp_path}/pub.sock")
    monkeypatch.setenv("AXO_ENDPOINT_SCRATCH_ROOT", str(tmp_path / "scratch"))

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
        assert register_result.metadata == {"function_id": "add", "version": 1}

        submit_result = _send_command(
            dealer,
            Command(
                operation=wire.JOB_SUBMIT,
                content_type="application/json",
                envelope={"function_id": "add", "function_name": "add", "function_version": 1, "params": {"a": 2, "b": 3}},
            ),
        )
        assert submit_result.ok is True
        assert submit_result.metadata["status"] == "QUEUED"
        job_id = submit_result.metadata["job_id"]

        final = _poll_until_terminal(dealer, job_id)
        assert final.ok is True
        assert final.metadata["status"] == "COMPLETED"
        assert final.metadata["values"] == {"value": 5}
    finally:
        dealer.close()
        app.stop()
        app_thread.join(timeout=5.0)
