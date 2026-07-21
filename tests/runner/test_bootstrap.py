import threading

import cloudpickle
import zmq

from axo_shared import wire
from axo_shared.protocol import CommandResult

from axo_endpoint.runner.bootstrap import fetch_code, materialize_function


def _run_fake_endpoint(bind_address, payload, metadata):
    ctx = zmq.Context.instance()
    router = ctx.socket(zmq.ROUTER)
    router.setsockopt(zmq.RCVTIMEO, 3000)
    router.bind(bind_address)

    def _serve():
        frames = router.recv_multipart()
        identity, body = frames[0], frames[1:]
        command = wire.decode_command(body).unwrap()
        assert command.operation == wire.CONTAINER_BOOTSTRAP
        result = CommandResult(ok=True, payload=payload, metadata=metadata)
        router.send_multipart([identity, *wire.encode_command_result(result)])
        router.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return thread


def test_fetch_code_returns_pickle_format_and_requirements(tmp_path):
    ctx = zmq.Context.instance()
    probe = ctx.socket(zmq.ROUTER)
    probe.bind("tcp://127.0.0.1:0")
    address = probe.getsockopt(zmq.LAST_ENDPOINT).decode("utf-8")
    probe.close()

    payload = cloudpickle.dumps(lambda params, ctx: params["a"] + params["b"])
    thread = _run_fake_endpoint(address, payload, {"requirements": ["numpy"], "code_format": "cloudpickle", "name": "add"})

    code_bytes, code_format, requirements, name = fetch_code(address, "add", 1)
    thread.join(timeout=2.0)

    assert code_bytes == payload
    assert code_format == "cloudpickle"
    assert requirements == ["numpy"]
    assert name == "add"


def test_fetch_code_defaults_name_to_function_id_when_absent():
    """An endpoint that hasn't been upgraded yet won't send "name" in
    metadata -- fall back to function_id rather than raising, matching the
    same defensive .get(..., default) pattern as requirements/code_format."""
    ctx = zmq.Context.instance()
    probe = ctx.socket(zmq.ROUTER)
    probe.bind("tcp://127.0.0.1:0")
    address = probe.getsockopt(zmq.LAST_ENDPOINT).decode("utf-8")
    probe.close()

    thread = _run_fake_endpoint(address, b"pickled-bytes", {})

    _, _, _, name = fetch_code(address, "add", 1)
    thread.join(timeout=2.0)

    assert name == "add"


def test_fetch_code_defaults_format_to_cloudpickle_when_absent():
    ctx = zmq.Context.instance()
    probe = ctx.socket(zmq.ROUTER)
    probe.bind("tcp://127.0.0.1:0")
    address = probe.getsockopt(zmq.LAST_ENDPOINT).decode("utf-8")
    probe.close()

    thread = _run_fake_endpoint(address, b"pickled-bytes", {})

    _, code_format, _, _ = fetch_code(address, "add", 1)
    thread.join(timeout=2.0)

    assert code_format == "cloudpickle"


def test_materialize_function_unpickles_for_cloudpickle_format():
    payload = cloudpickle.dumps(lambda params, ctx: params["a"] + params["b"])
    fn = materialize_function(payload, "cloudpickle", "add")
    assert fn({"a": 2, "b": 3}, None) == 5


def test_materialize_function_execs_source_for_source_format():
    source = b"def add(params, ctx):\n    return params['a'] + params['b']\n"
    fn = materialize_function(source, "source", "add")
    assert fn({"a": 2, "b": 3}, None) == 5
