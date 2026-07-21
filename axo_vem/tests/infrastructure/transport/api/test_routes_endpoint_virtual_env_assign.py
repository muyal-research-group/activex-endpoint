import threading

import zmq

from axo_shared import wire


def _run_fake_endpoint(bind_address, reply_ok, error_message=""):
    ctx = zmq.Context.instance()
    router = ctx.socket(zmq.ROUTER)
    router.setsockopt(zmq.RCVTIMEO, 3000)
    router.bind(bind_address)

    def _serve():
        frames = router.recv_multipart()
        identity, body = frames[0], frames[1:]
        command = wire.decode_command(body).unwrap()
        assert command.operation == wire.VIRTUAL_ENV_ASSIGN
        from axo_shared.protocol import CommandResult
        result = CommandResult(ok=reply_ok, error=error_message)
        router.send_multipart([identity, *wire.encode_command_result(result)])
        router.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return thread


def test_assign_forwards_command_and_relays_success(client, collections):
    ctx = zmq.Context.instance()
    probe = ctx.socket(zmq.ROUTER)
    probe.bind("tcp://127.0.0.1:0")
    address = probe.getsockopt(zmq.LAST_ENDPOINT).decode("utf-8")
    probe.close()

    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})
    thread = _run_fake_endpoint(address, reply_ok=True)

    response = client.post("/endpoints/127.0.0.1/virtual-environment", json={"virtual_environment_id": "ve1"})
    thread.join(timeout=2.0)

    assert response.status_code == 200
    assert response.json() == {"endpoint_id": "127.0.0.1", "virtual_environment_id": "ve1"}


def test_assign_relays_rejection_as_409(client, collections):
    ctx = zmq.Context.instance()
    probe = ctx.socket(zmq.ROUTER)
    probe.bind("tcp://127.0.0.1:0")
    address = probe.getsockopt(zmq.LAST_ENDPOINT).decode("utf-8")
    probe.close()

    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})
    thread = _run_fake_endpoint(address, reply_ok=False, error_message="endpoint has active jobs")

    response = client.post("/endpoints/127.0.0.1/virtual-environment", json={"virtual_environment_id": "ve1"})
    thread.join(timeout=2.0)

    assert response.status_code == 409
    assert response.json()["detail"] == "endpoint has active jobs"


def test_assign_returns_404_for_unknown_endpoint(client):
    response = client.post("/endpoints/missing/virtual-environment", json={"virtual_environment_id": "ve1"})
    assert response.status_code == 404


def test_assign_times_out_when_endpoint_unreachable(client, collections):
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": "tcp://127.0.0.1:59999"})

    response = client.post("/endpoints/127.0.0.1/virtual-environment", json={"virtual_environment_id": "ve1"})

    assert response.status_code == 504
