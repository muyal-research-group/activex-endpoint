from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Optional

import cloudpickle
import zmq
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from axo_endpoint.core.dataio import DataIOError, DataIOTimeoutError, IORef
from axo_endpoint.core.results import is_json_safe_value
from axo_endpoint.core.runtime import InvocationContext
from axo_endpoint.dataio import bind_channel, reset_channel
from axo_endpoint.runner.job_store import JobStore


def _encode_result(value: Any) -> bytes:
    """JSON-encodes a function's raw return if it's JSON-safe; otherwise
    cloudpickles it. The receiving endpoint's own build_completion_recorder
    mirrors this exact fallback (json.loads failing on the payload is what
    tells it the bytes are a cloudpickled blob, not JSON), so no extra tag
    is needed on the wire -- the bytes themselves are self-describing."""
    if is_json_safe_value(value):
        return json.dumps(value).encode("utf-8")
    return cloudpickle.dumps(value)

logger = logging.getLogger("axo.runner.server")


class ZmqIOChannel:
    """Lets a running function reach back to the endpoint mid-job over the
    same ROUTER socket/peer identity the job dispatch arrived on."""

    def __init__(self, sock: "zmq.Socket", identity: bytes, timeout_ms: int) -> None:
        self._sock = sock
        self._identity = identity
        self._timeout_ms = timeout_ms

    def request(self, op: str, ref: IORef, data: Optional[bytes]) -> bytes:
        request_id = uuid.uuid4().hex.encode()
        self._sock.send_multipart([
            self._identity, b"io_request", request_id,
            op.encode(), json.dumps(ref.to_dict()).encode(), data or b"",
        ])
        prev_timeout = self._sock.getsockopt(zmq.RCVTIMEO)
        self._sock.setsockopt(zmq.RCVTIMEO, self._timeout_ms)
        try:
            while True:
                try:
                    frames = self._sock.recv_multipart()
                except zmq.Again as exc:
                    raise DataIOTimeoutError(f"no io reply within {self._timeout_ms}ms") from exc
                if len(frames) == 5 and frames[1] == b"io_reply" and frames[2] == request_id:
                    _, _, _, status_b, payload_b = frames
                    break
        finally:
            self._sock.setsockopt(zmq.RCVTIMEO, prev_timeout)

        if status_b != b"ok":
            raise DataIOError(payload_b.decode("utf-8", errors="replace"))
        return payload_b


class InvokeRequest(BaseModel):
    params: Dict[str, Any] = {}


class RunnerServer:
    """Hosts the ZMQ ROUTER (for endpoint job dispatch) and FastAPI (for direct invocation)."""

    def __init__(
        self,
        fn: Callable[..., Any],
        job_store: JobStore,
        job_port: int,
        fastapi_port: int,
        result_address: Optional[str] = None,
        scratch_root: str = "/tmp/axo_runner/scratch",
        function_id: str = "unknown",
        dataio_timeout_seconds: float = 30.0,
    ) -> None:
        self._fn = fn
        self._store = job_store
        self._job_port = job_port
        self._fastapi_port = fastapi_port
        self._result_address = result_address
        self._scratch_root = scratch_root
        self._function_id = function_id
        self._dataio_timeout_ms = int(dataio_timeout_seconds * 1000)
        self._ready = False
        self._shutdown = threading.Event()

        # Optional result-push socket (to endpoint PULL)
        self._result_sock: Optional[zmq.Socket] = None

    def start(self) -> None:
        """Starts both servers and blocks until shutdown is signalled."""
        zmq_thread = threading.Thread(target=self._run_zmq, daemon=True)
        zmq_thread.start()

        if self._result_address:
            self._result_sock = zmq.Context.instance().socket(zmq.PUSH)
            self._result_sock.connect(self._result_address)

        self._ready = True
        logger.info("runner ready: zmq_port=%d fastapi_port=%d", self._job_port, self._fastapi_port)

        import uvicorn
        app = self._build_fastapi()
        config = uvicorn.Config(app, host="0.0.0.0", port=self._fastapi_port, log_level="warning")
        server = uvicorn.Server(config)
        server.run()

    # ── ZMQ ROUTER (endpoint job dispatch) ─────────────────────────────────────

    def _run_zmq(self) -> None:
        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.ROUTER)
        sock.setsockopt(zmq.RCVTIMEO, 200)
        sock.bind(f"tcp://0.0.0.0:{self._job_port}")
        logger.info("ZMQ ROUTER bound on port %d", self._job_port)

        while not self._shutdown.is_set():
            try:
                frames = sock.recv_multipart()
            except zmq.Again:
                continue
            except zmq.ZMQError:
                break

            # ROUTER frames: [identity, b"dispatch", job_id, scratch_dir, params_json]
            if len(frames) < 5 or frames[1] != b"dispatch":
                continue

            identity, _tag, job_id_b, scratch_dir_b, params_b = (
                frames[0], frames[1], frames[2], frames[3], frames[4]
            )
            job_id = job_id_b.decode("utf-8")
            scratch_dir = scratch_dir_b.decode("utf-8")

            logger.debug("zmq job received job_id=%s", job_id)
            self._store.set_pending(job_id)

            ctx = InvocationContext(job_id=job_id, scratch_dir=scratch_dir)
            token = bind_channel(ZmqIOChannel(sock, identity, self._dataio_timeout_ms))
            try:
                params = json.loads(params_b.decode("utf-8"))
                result = self._fn(params, ctx)
                payload = _encode_result(result)
                output = {"value": result, "type": "json"} if is_json_safe_value(result) else {"type": "bytes"}
                self._store.set_result(job_id, ok=True, output=output, warnings=ctx.warnings)
                # No _push_result here: this reply already delivers the result
                # over the same connection the job arrived on. _push_result's
                # PUSH channel exists only for the /invoke path below, which
                # has no such connection to reply on.
                warnings_payload = json.dumps(ctx.warnings).encode("utf-8")
                sock.send_multipart([identity, b"result", job_id_b, b"ok", payload, warnings_payload])
            except Exception as exc:
                error = str(exc)
                logger.warning("zmq job failed job_id=%s error=%s", job_id, error)
                self._store.set_result(job_id, ok=False, error=error, warnings=ctx.warnings)
                warnings_payload = json.dumps(ctx.warnings).encode("utf-8")
                sock.send_multipart([identity, b"result", job_id_b, b"err", error.encode(), warnings_payload])
            finally:
                reset_channel(token)

        sock.close()

    def _push_result(self, job_id: str, status: str, payload: bytes) -> None:
        if not self._result_sock:
            return
        try:
            self._result_sock.send_multipart(
                [
                    job_id.encode(),
                    self._function_id.encode(),
                    status.encode(),
                    payload,
                ],
                flags=zmq.NOBLOCK,
            )
        except zmq.ZMQError:
            pass  # best-effort

    # ── FastAPI (direct user invocation) ───────────────────────────────────────

    def _build_fastapi(self) -> FastAPI:
        store = self._store
        fn = self._fn
        scratch_root = self._scratch_root
        function_id = self._function_id
        push_result = self._push_result
        ready_ref = self

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            yield

        app = FastAPI(title=f"axo-runner [{function_id}]", lifespan=lifespan)

        @app.get("/health")
        async def health():
            if not ready_ref._ready:
                raise HTTPException(status_code=503, detail="bootstrapping")
            return {"status": "ok", "function_id": function_id}

        @app.post("/invoke")
        async def invoke(body: InvokeRequest):
            job_id = uuid.uuid4().hex
            store.set_pending(job_id)

            def _run():
                scratch_dir = os.path.join(scratch_root, job_id)
                os.makedirs(scratch_dir, exist_ok=True)
                # No IOChannel bound here (unlike the ZMQ dispatch path): direct
                # HTTP invocation has no endpoint round trip to proxy dataio
                # requests through, so dataio.read/write raises DataIOUnavailableError.
                ctx = InvocationContext(job_id=job_id, scratch_dir=scratch_dir)
                try:
                    result = fn(body.params, ctx)
                    output = {"value": result, "type": "json"} if is_json_safe_value(result) else {"type": "bytes"}
                    store.set_result(job_id, ok=True, output=output, warnings=ctx.warnings)
                    push_result(job_id, "ok", _encode_result(result))
                except Exception as exc:
                    error = str(exc)
                    store.set_result(job_id, ok=False, error=error, warnings=ctx.warnings)
                    push_result(job_id, "err", error.encode())

            threading.Thread(target=_run, daemon=True).start()
            return {"job_id": job_id}

        @app.get("/jobs/{job_id}")
        async def get_job(job_id: str):
            entry = store.get(job_id)
            if entry is None:
                raise HTTPException(status_code=404, detail="job not found")
            return {
                "job_id": entry.job_id,
                "status": entry.status,
                "output": entry.output,
                "warnings": entry.warnings,
                "error": entry.error,
            }

        @app.delete("/")
        async def shutdown():
            ready_ref._shutdown.set()
            return {"status": "shutting down"}

        return app
