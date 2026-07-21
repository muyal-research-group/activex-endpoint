from __future__ import annotations

import json
import threading
from typing import Callable, Union

import zmq

from axo_endpoint.core.runtime.base import FunctionRuntimeError, InvocationHandle
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]

# Frame layout from container runner: [job_id, function_id, status, payload_json]
_FRAME_COUNT = 4


class ContainerResultReceiver:
    """ZMQ PULL socket that receives job results pushed by container runners.

    Used by the FastAPI direct-invocation path so the endpoint's results_store
    stays consistent regardless of how the function was called.
    """

    def __init__(
        self,
        bind_address: str,
        on_result: Callable[[InvocationHandle, object], None],
        logger: _Logger = None,
    ) -> None:
        self._bind_address = bind_address
        self._on_result = on_result
        self._logger: _Logger = logger or DumbLogger()
        self._running = False
        self._thread: threading.Thread | None = None
        self._socket: zmq.Socket | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._socket:
            self._socket.close()

    def _run(self) -> None:
        ctx = zmq.Context.instance()
        self._socket = ctx.socket(zmq.PULL)
        self._socket.setsockopt(zmq.RCVTIMEO, 200)
        self._socket.bind(self._bind_address)

        while self._running:
            try:
                frames = self._socket.recv_multipart()
            except zmq.Again:
                continue
            except zmq.ZMQError:
                break

            if len(frames) != _FRAME_COUNT:
                self._logger.warning_event(
                    Event.Container.RESULT_PUSHED,
                    component=Component.RESULT_RECEIVER,
                    status="error",
                    error_message=f"expected {_FRAME_COUNT} frames, got {len(frames)}",
                )
                continue

            job_id_b, function_id_b, status_b, payload_b = frames
            job_id = job_id_b.decode("utf-8")
            function_id = function_id_b.decode("utf-8")
            status = status_b.decode("utf-8")

            handle = InvocationHandle(job_id=job_id, function_id=function_id)

            if status == "ok":
                try:
                    value = json.loads(payload_b.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    value = payload_b
                from option import Ok
                self._on_result(handle, Ok(value))
            else:
                error_msg = payload_b.decode("utf-8", errors="replace")
                from option import Err
                self._on_result(handle, Err(FunctionRuntimeError(error_msg)))

            self._logger.debug_event(
                Event.Container.RESULT_PUSHED,
                component=Component.RESULT_RECEIVER,
                status="ok",
                job_id=job_id,
                function_id=function_id,
                result_status=status,
            )
