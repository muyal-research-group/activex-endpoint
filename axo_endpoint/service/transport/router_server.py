from __future__ import annotations

import time
import threading
from typing import Any, Callable, Dict, Optional, Union

import zmq

from axo_endpoint.core.events.bus import Event, EventBus
from axo_shared.protocol import CommandDispatcher, CommandHandler, CommandResult
from axo_endpoint.core.storage.backend import StorageBackend, StorageKey
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event
from axo_shared import wire

_Logger = Union[Log, DumbLogger]


class RouterServer:
    """Listens for requests from clients and sends back replies. Also sends
    a message on its own when a submitted job finishes."""

    def __init__(
        self,
        bind_address: str,
        direct_handlers: Dict[str, CommandHandler],
        dispatcher: CommandDispatcher,
        results: StorageBackend[StorageKey, Any],
        event_bus: EventBus,
        context: Optional["zmq.Context"] = None,
        on_request_fn: Optional[Callable[[], None]] = None,
        logger: _Logger = None,
    ) -> None:
        """Binds a socket so the server is ready to start handling requests."""
        self._context = context or zmq.Context.instance()
        self._socket = self._context.socket(zmq.ROUTER)
        self._socket.bind(bind_address)
        self._socket.setsockopt(zmq.RCVTIMEO, 200)  # ms -- lets the recv loop notice stop()

        self._direct_handlers = direct_handlers
        self._dispatcher = dispatcher
        self._results = results
        self._on_request_fn = on_request_fn
        self._logger: _Logger = logger or DumbLogger()

        self._send_lock = threading.Lock()
        self._job_identities: Dict[str, bytes] = {}
        self._job_identities_lock = threading.Lock()

        self._running = False
        self._thread: Optional[threading.Thread] = None

        event_bus.subscribe("JOB_COMPLETED", self._on_job_event)
        event_bus.subscribe("JOB_FAILED", self._on_job_event)

    def start(self) -> None:
        """Starts handling requests in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stops handling requests and closes the socket."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._socket.close()

    def _run(self) -> None:
        """Repeatedly waits for and processes incoming requests."""
        while self._running:
            try:
                frames = self._socket.recv_multipart()
            except zmq.Again:
                continue
            except zmq.ZMQError:
                break
            identity, *body = frames
            self._handle_request(identity, body)

    def _handle_request(self, identity: bytes, body: list) -> None:
        """Decodes one request, runs the right handler, and sends back the reply."""
        decode_result = wire.decode_command(body)
        if decode_result.is_err:
            err = decode_result.unwrap_err()
            self._logger.debug_event(
                Event.Router.REQUEST_DROPPED,
                component=Component.ROUTER,
                frame_count=len(body),
                **err.to_dict(),
            )
            return  # nothing sane to reply with to an unparseable request

        command = decode_result.unwrap()
        self._logger.debug_event(
            Event.Router.REQUEST_RECEIVED,
            component=Component.ROUTER,
            operation=command.operation,
            content_type=command.content_type,
            envelope=command.envelope,
        )

        if self._on_request_fn is not None:
            self._on_request_fn()

        t0 = time.monotonic()
        handler = self._direct_handlers.get(command.operation)
        if handler is not None:
            result = handler.handle(command)
            duration_ms = round((time.monotonic() - t0) * 1000, 2)
            self._logger.info_event(
                Event.Router.REQUEST_HANDLED,
                component=Component.ROUTER,
                operation=command.operation,
                status="ok" if result.ok else "error",
                duration_ms=duration_ms,
            )
        else:
            result = self._dispatcher.submit(command)
            duration_ms = round((time.monotonic() - t0) * 1000, 2)
            self._logger.info_event(
                Event.Router.REQUEST_DISPATCHED,
                component=Component.ROUTER,
                operation=command.operation,
                status="ok" if result.ok else "error",
                duration_ms=duration_ms,
            )

        if command.operation == wire.JOB_SUBMIT and result.ok:
            job_id = result.metadata.get("job_id")
            if job_id:
                with self._job_identities_lock:
                    self._job_identities[job_id] = identity

        if command.operation == wire.JOB_RESULT and result.ok and result.metadata.get("status") in (
            "COMPLETED",
            "FAILED",
        ):
            job_id = command.envelope.get("job_id")
            if job_id:
                with self._job_identities_lock:
                    self._job_identities.pop(job_id, None)

        self._send(identity, result)

    def _send(self, identity: bytes, result: CommandResult) -> None:
        """Sends a reply back to a specific client."""
        frames = wire.encode_command_result(result)
        with self._send_lock:
            self._socket.send_multipart([identity, *frames])

    def _on_job_event(self, event: Event) -> None:
        """Pushes a job's result to its client when the job finishes, if the client is still known."""
        job_id = event.payload.get("job_id")
        if job_id is None:
            return

        with self._job_identities_lock:
            identity = self._job_identities.pop(job_id, None)
        if identity is None:
            self._logger.debug_event(
                Event.Router.PUSH_SKIPPED,
                component=Component.ROUTER,
                job_id=job_id,
                event_type=event.event_type,
            )
            return  # never submitted through this transport instance, or already fetched via poll

        get_result = self._results.get(StorageKey(id=job_id))
        if get_result.is_err:
            return
        function_result = get_result.unwrap()
        if function_result is None:
            return

        push_result = CommandResult(
            ok=function_result.ok,
            error=function_result.error,
            metadata={
                "job_id": job_id,
                "status": "COMPLETED" if function_result.ok else "FAILED",
                "output": function_result.output,
                "refs": {k: v.to_str() for k, v in function_result.refs.items()},
                "duration_ms": function_result.duration_ms,
                "warnings": function_result.warnings,
                "pushed": True,
            },
        )
        self._logger.debug_event(
            Event.Router.PUSH_SENT,
            component=Component.ROUTER,
            job_id=job_id,
            event_type=event.event_type,
        )
        self._send(identity, push_result)
