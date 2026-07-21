import threading

import zmq

from axo_shared import wire
from axo_shared.functions.identity import compute_function_id

from .conftest import FAKE_USER


def _run_fake_endpoint(bind_address, reply_ok, error_message="", metadata=None):
    ctx = zmq.Context.instance()
    router = ctx.socket(zmq.ROUTER)
    router.setsockopt(zmq.RCVTIMEO, 3000)
    router.bind(bind_address)

    captured = {}

    def _serve():
        frames = router.recv_multipart()
        identity, body = frames[0], frames[1:]
        command = wire.decode_command(body).unwrap()
        captured["command"] = command
        from axo_shared.protocol import CommandResult
        result = CommandResult(ok=reply_ok, error=error_message, metadata=metadata or {})
        router.send_multipart([identity, *wire.encode_command_result(result)])
        router.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return thread, captured


def _source_for(function_name: str) -> bytes:
    return (
        f"def {function_name}(params, ctx):\n"
        f"    return {{'sum': params['a'] + params['b']}}\n"
    ).encode()


def _create_ve(client, name="dev-env", cpu=2.0, ram=1024, disk=2048):
    return client.post("/virtual-environments", json={"name": name, "cpu": cpu, "ram": ram, "disk": disk})


def _bind_probe():
    ctx = zmq.Context.instance()
    probe = ctx.socket(zmq.ROUTER)
    probe.bind("tcp://127.0.0.1:0")
    address = probe.getsockopt(zmq.LAST_ENDPOINT).decode("utf-8")
    probe.close()
    return address


def test_register_function_validates_source_and_forwards_it_untouched(client, collections):
    address = _bind_probe()
    ve_id = _create_ve(client).json()["virtual_environment_id"]

    # endpoint_id is set to the resolvable loopback host itself -- proves the
    # use case connects to <endpoint_id>:<port>, not whatever host is
    # stored in router_bind (see test below for the case where those differ).
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address, "virtual_environment_id": ve_id})
    thread, captured = _run_fake_endpoint(address, reply_ok=True, metadata={"function_id": "add", "version": 1})

    source = _source_for("add")
    response = client.post(
        "/functions",
        data={"virtual_environment_id": ve_id, "name": "add", "runtime_spec": '{"type": "process"}'},
        files={"code": ("add.py", source, "text/x-python")},
    )
    thread.join(timeout=2.0)

    assert response.status_code == 201
    body = response.json()
    assert body["endpoint_id"] == "127.0.0.1"
    assert body["name"] == "add"
    assert body["version"] == 1

    command = captured["command"]
    assert command.operation == wire.FUNCTION_REGISTER
    assert command.envelope["name"] == "add"
    assert command.envelope["function_id"] == compute_function_id(FAKE_USER.key, ve_id, "add")
    assert command.envelope["runtime_spec"] == {"type": "process"}
    assert command.envelope["code_format"] == "source"

    # This service never executes or pickles the upload -- the forwarded
    # payload must be the exact raw source bytes, verbatim.
    assert command.payload == source


def test_register_function_ignores_router_bind_host_and_uses_endpoint_id(client, collections):
    address = _bind_probe()
    port = address.rsplit(":", 1)[-1]
    ve_id = _create_ve(client).json()["virtual_environment_id"]

    # router_bind carries the real production shape (an unconnectable bind
    # address) while endpoint_id is the resolvable host -- this only
    # succeeds if the use case builds the connect target from endpoint_id,
    # not from router_bind's own host part.
    collections.endpoints.insert_one({
        "_id": "127.0.0.1", "router_bind": f"tcp://0.0.0.0:{port}", "virtual_environment_id": ve_id,
    })
    thread, captured = _run_fake_endpoint(address, reply_ok=True, metadata={"function_id": "add", "version": 1})

    response = client.post(
        "/functions",
        data={"virtual_environment_id": ve_id, "name": "add"},
        files={"code": ("add.py", _source_for("add"), "text/x-python")},
    )
    thread.join(timeout=2.0)

    assert response.status_code == 201
    assert captured["command"].operation == wire.FUNCTION_REGISTER


def test_register_function_relays_rejection_as_409(client, collections):
    address = _bind_probe()
    ve_id = _create_ve(client).json()["virtual_environment_id"]

    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address, "virtual_environment_id": ve_id})
    thread, _ = _run_fake_endpoint(address, reply_ok=False, error_message="storage failure")

    response = client.post(
        "/functions",
        data={"virtual_environment_id": ve_id, "name": "add"},
        files={"code": ("add.py", _source_for("add"), "text/x-python")},
    )
    thread.join(timeout=2.0)

    assert response.status_code == 409
    assert response.json()["detail"] == "storage failure"


def test_register_function_returns_404_for_unknown_virtual_environment(client):
    response = client.post(
        "/functions",
        data={"virtual_environment_id": "missing", "name": "add"},
        files={"code": ("add.py", _source_for("add"), "text/x-python")},
    )
    assert response.status_code == 404


def test_register_function_returns_409_when_ve_has_no_endpoint_assigned(client):
    ve_id = _create_ve(client).json()["virtual_environment_id"]

    response = client.post(
        "/functions",
        data={"virtual_environment_id": ve_id, "name": "add"},
        files={"code": ("add.py", _source_for("add"), "text/x-python")},
    )

    assert response.status_code == 409
    assert "no endpoint assigned" in response.json()["detail"]


def test_register_function_returns_403_for_foreign_virtual_environment(client, db):
    db["virtual_environments"].insert_one({
        "_id": "ve-other", "virtual_environment_id": "ve-other", "name": "not-mine",
        "owner_user_id": "someone-else", "resource_quota": {"cpu": 1.0, "ram": 512, "disk": 1024},
    })

    response = client.post(
        "/functions",
        data={"virtual_environment_id": "ve-other", "name": "add"},
        files={"code": ("add.py", _source_for("add"), "text/x-python")},
    )

    assert response.status_code == 403


def test_register_function_returns_422_for_invalid_runtime_spec_json(client):
    # 422 validation happens before any VE/endpoint lookup, so no VE needs
    # to exist for this case.
    response = client.post(
        "/functions",
        data={"virtual_environment_id": "missing", "name": "add", "runtime_spec": "not-json"},
        files={"code": ("add.py", _source_for("add"), "text/x-python")},
    )

    assert response.status_code == 422


def test_register_function_returns_422_for_syntax_error(client):
    response = client.post(
        "/functions",
        data={"virtual_environment_id": "missing", "name": "add"},
        files={"code": ("add.py", b"def add(params, ctx:\n    pass\n", "text/x-python")},
    )

    assert response.status_code == 422
    assert "syntax error" in response.json()["detail"]


def test_register_function_returns_422_when_name_not_defined_in_source(client):
    response = client.post(
        "/functions",
        data={"virtual_environment_id": "missing", "name": "add"},
        files={"code": ("add.py", _source_for("subtract"), "text/x-python")},
    )

    assert response.status_code == 422
    assert "add" in response.json()["detail"]


def test_register_function_times_out_when_endpoint_unreachable(client, collections):
    ve_id = _create_ve(client).json()["virtual_environment_id"]
    collections.endpoints.insert_one({
        "_id": "127.0.0.1", "router_bind": "tcp://127.0.0.1:59998", "virtual_environment_id": ve_id,
    })

    response = client.post(
        "/functions",
        data={"virtual_environment_id": ve_id, "name": "add"},
        files={"code": ("add.py", _source_for("add"), "text/x-python")},
    )

    assert response.status_code == 504


def test_delete_function_forwards_command_and_relays_success(client, collections):
    address = _bind_probe()
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})
    collections.functions.insert_one({
        "_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["127.0.0.1"],
    })
    thread, captured = _run_fake_endpoint(address, reply_ok=True, metadata={"function_id": "add", "version": 1})

    response = client.delete("/functions/add/1")
    thread.join(timeout=2.0)

    assert response.status_code == 200
    assert response.json() == {"function_id": "add", "version": 1}

    command = captured["command"]
    assert command.operation == wire.FUNCTION_DELETE
    assert command.envelope == {"function_id": "add", "version": 1}


def test_delete_function_relays_rejection_as_409(client, collections):
    address = _bind_probe()
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})
    collections.functions.insert_one({
        "_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["127.0.0.1"],
    })
    thread, _ = _run_fake_endpoint(address, reply_ok=False, error_message="function not found")

    response = client.delete("/functions/add/1")
    thread.join(timeout=2.0)

    assert response.status_code == 409
    assert response.json()["detail"] == "function not found"


def test_delete_function_returns_404_for_unknown_function(client):
    response = client.delete("/functions/missing/1")
    assert response.status_code == 404


def test_delete_function_times_out_when_endpoint_unreachable(client, collections):
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": "tcp://127.0.0.1:59998"})
    collections.functions.insert_one({
        "_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["127.0.0.1"],
    })

    response = client.delete("/functions/add/1")

    assert response.status_code == 504


def test_delete_function_routes_via_recorded_endpoint_despite_ve_mismatched_endpoint_present(client, collections):
    """Regression test for the original bug: deleting used to re-derive
    function_id from a caller-picked endpoint's virtual_environment_id, so
    picking (or defaulting to) an endpoint with a different VE than the one
    used at register time permanently failed with "no FunctionRecord found".
    Now routing depends only on the function's own recorded endpoint_id --
    a second, VE-mismatched endpoint existing in the cluster must have no
    effect on the outcome."""
    address = _bind_probe()
    # The function's real, recorded endpoint.
    collections.endpoints.insert_one({
        "_id": "127.0.0.1", "router_bind": address, "virtual_environment_id": "ve-a",
    })
    # A decoy endpoint in a totally different VE -- must never be contacted.
    collections.endpoints.insert_one({
        "_id": "decoy", "router_bind": "tcp://127.0.0.1:59997", "virtual_environment_id": "ve-b",
    })
    collections.functions.insert_one({
        "_id": "add:1", "function_id": "add", "version": 1, "endpoint_id": ["127.0.0.1"],
    })
    thread, captured = _run_fake_endpoint(address, reply_ok=True, metadata={"function_id": "add", "version": 1})

    response = client.delete("/functions/add/1")
    thread.join(timeout=2.0)

    assert response.status_code == 200
    assert captured["command"].operation == wire.FUNCTION_DELETE
