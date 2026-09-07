import contextlib
import json
import socket
import threading
import time
import uuid

import zmq

from axo_endpoint.runner.job_store import JobStore
from axo_endpoint.runner.server import RunnerServer


def _free_tcp_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_zmq_only(fn, dataio_timeout_seconds=30.0):
    """Starts just RunnerServer's ZMQ ROUTER loop, skipping the blocking
    uvicorn/FastAPI half of start()."""
    job_port = _free_tcp_port()
    server = RunnerServer(
        fn=fn,
        job_store=JobStore(),
        job_port=job_port,
        fastapi_port=_free_tcp_port(),
        function_id="test",
        dataio_timeout_seconds=dataio_timeout_seconds,
    )
    thread = threading.Thread(target=server._run_zmq, daemon=True)
    thread.start()
    time.sleep(0.1)  # let the ROUTER bind
    return server, job_port


def _dealer(job_port):
    sock = zmq.Context.instance().socket(zmq.DEALER)
    sock.setsockopt(zmq.RCVTIMEO, 5000)
    sock.connect(f"tcp://127.0.0.1:{job_port}")
    return sock


def _start_zmq_with_result_push(fn):
    """Like _start_zmq_only, but also wires up the PUSH-to-endpoint result
    socket the same way start() does -- _run_zmq itself never touches
    _result_sock, start() sets it up before running the blocking uvicorn
    loop, so tests bypassing start() must do that part by hand."""
    result_port = _free_tcp_port()
    pull_sock = zmq.Context.instance().socket(zmq.PULL)
    pull_sock.setsockopt(zmq.RCVTIMEO, 300)
    pull_sock.bind(f"tcp://127.0.0.1:{result_port}")

    job_port = _free_tcp_port()
    server = RunnerServer(
        fn=fn,
        job_store=JobStore(),
        job_port=job_port,
        fastapi_port=_free_tcp_port(),
        result_address=f"tcp://127.0.0.1:{result_port}",
        function_id="test",
    )
    server._result_sock = zmq.Context.instance().socket(zmq.PUSH)
    server._result_sock.connect(server._result_address)

    thread = threading.Thread(target=server._run_zmq, daemon=True)
    thread.start()
    time.sleep(0.1)  # let the ROUTER bind
    return server, job_port, pull_sock


def test_dispatch_result_happy_path():
    server, job_port = _start_zmq_only(fn=lambda params, ctx: params["a"] + params["b"])
    sock = _dealer(job_port)
    try:
        sock.send_multipart([b"dispatch", b"job1", b"/tmp/scratch1", json.dumps({"a": 2, "b": 3}).encode()])
        frames = sock.recv_multipart()
        assert frames[0] == b"result"
        assert len(frames) == 5
        _, job_id_b, status_b, payload_b, warnings_b = frames
        assert job_id_b == b"job1"
        assert status_b == b"ok"
        assert json.loads(payload_b.decode()) == 5
        assert json.loads(warnings_b.decode()) == []
    finally:
        sock.close()
        server._shutdown.set()


def test_normal_dispatch_does_not_push_to_result_socket():
    """Regression test: the ZMQ dispatch reply already delivers the result --
    _push_result must not also fire on this path (it exists only for the
    /invoke path below, which has no other way to report back). A prior bug
    called it unconditionally here too, double-delivering every job's
    completion to the endpoint."""
    server, job_port, pull_sock = _start_zmq_with_result_push(
        fn=lambda params, ctx: params["a"] + params["b"]
    )
    sock = _dealer(job_port)
    try:
        sock.send_multipart([b"dispatch", b"job1", b"/tmp/scratch1", json.dumps({"a": 2, "b": 3}).encode()])
        frames = sock.recv_multipart()
        assert frames[0] == b"result"

        try:
            pull_sock.recv_multipart()
            assert False, "expected no message on the result-push socket"
        except zmq.Again:
            pass
    finally:
        sock.close()
        pull_sock.close()
        server._shutdown.set()


def _fn_reads_dataio(params, ctx):
    from axo_endpoint import dataio
    from axo_endpoint.core.dataio import IORef

    value = dataio.read(IORef(kind="fs", location=params["location"], format="raw"))
    return value.decode("utf-8")


def test_fn_dataio_read_triggers_io_request_and_resumes_on_reply():
    server, job_port = _start_zmq_only(fn=_fn_reads_dataio)
    sock = _dealer(job_port)
    try:
        sock.send_multipart([
            b"dispatch", b"job1", b"/tmp/scratch1", json.dumps({"location": "in.bin"}).encode(),
        ])

        frames = sock.recv_multipart()
        assert frames[0] == b"io_request"
        assert len(frames) == 5
        _, request_id_b, op_b, ref_json_b, data_b = frames
        assert op_b == b"read"
        ref = json.loads(ref_json_b.decode())
        assert ref == {"kind": "fs", "location": "in.bin", "format": "raw", "chunk_index": None}

        sock.send_multipart([b"io_reply", request_id_b, b"ok", b"canned-bytes"])

        frames = sock.recv_multipart()
        assert frames[0] == b"result"
        _, job_id_b, status_b, payload_b, warnings_b = frames
        assert status_b == b"ok"
        assert json.loads(payload_b.decode()) == "canned-bytes"
    finally:
        sock.close()
        server._shutdown.set()


def _fn_writes_dataio(params, ctx):
    from axo_endpoint import dataio
    from axo_endpoint.core.dataio import IORef

    dataio.write(b"payload-bytes", IORef(kind="fs", location=params["location"], format="raw"))
    return "written"


def test_dataio_timeout_surfaces_as_job_failure_not_a_hang():
    server, job_port = _start_zmq_only(fn=_fn_writes_dataio, dataio_timeout_seconds=0.3)
    sock = _dealer(job_port)
    try:
        sock.send_multipart([
            b"dispatch", b"job1", b"/tmp/scratch1", json.dumps({"location": "out.bin"}).encode(),
        ])

        frames = sock.recv_multipart()
        assert frames[0] == b"io_request"  # never reply -- force the timeout

        frames = sock.recv_multipart()  # bounded by the socket's own 5s RCVTIMEO
        assert frames[0] == b"result"
        _, job_id_b, status_b, payload_b, warnings_b = frames
        assert status_b == b"err"
        assert "no io reply within" in payload_b.decode()
    finally:
        sock.close()
        server._shutdown.set()


def test_direct_invoke_http_path_has_no_dataio_channel():
    from fastapi.testclient import TestClient

    def fn(params, ctx):
        from axo_endpoint import dataio
        from axo_endpoint.core.dataio import IORef
        return dataio.read(IORef(kind="fs", location="x", format="raw")).decode()

    server = RunnerServer(
        fn=fn,
        job_store=JobStore(),
        job_port=_free_tcp_port(),
        fastapi_port=_free_tcp_port(),
        function_id="test",
    )
    app = server._build_fastapi()
    client = TestClient(app)

    resp = client.post("/invoke", json={"params": {}})
    job_id = resp.json()["job_id"]

    deadline = time.time() + 5.0
    entry = None
    while time.time() < deadline:
        entry = server._store.get(job_id)
        if entry is not None and entry.status != "PENDING":
            break
        time.sleep(0.02)

    assert entry is not None
    assert entry.status == "FAILED"
    assert "DATAIO_UNAVAILABLE" in entry.error or "no active job io channel" in entry.error
