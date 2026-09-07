from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Union

import zmq

from axo_shared.events.envelope import encode_event
from axo_shared.wire import encode_command
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class ZmqEventPublisher:
    """Fire-and-forget DEALER client that forwards taxonomy events to
    axo_vem. Never calls recv_multipart -- a slow or unreachable
    API is bounded by ZMQ's own send-side buffering/high-water-mark, never by
    blocking the caller, which is typically a bus subscriber reacting
    synchronously to a lifecycle event on the hot path (e.g.
    FunctionRegistry.register()).

    One instance is shared across many threads (the heartbeat loop, router
    thread, dispatcher workers all call publish() as a side effect of
    reacting to bus events) -- a zmq socket is not itself thread-safe for
    concurrent send_multipart calls, so every send is serialized through
    ``_lock``. Without this, concurrent sends interleave frames from
    different messages on the wire (observed as spurious "wrong frame
    count" decode errors on the receiving end).
    """

    def __init__(
        self,
        api_uri: str,
        endpoint_id: str,
        context: Optional["zmq.Context"] = None,
        logger: _Logger = None,
    ) -> None:
        self._endpoint_id = endpoint_id
        self._context = context or zmq.Context.instance()
        self._socket = self._context.socket(zmq.DEALER)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.connect(api_uri)
        self._logger: _Logger = logger or DumbLogger()
        self._lock = threading.Lock()

    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """Encodes and sends one event. Never blocks or raises if the API is
        slow, unreachable, or the send buffer is full."""
        command = encode_event(event_type, self._endpoint_id, data)
        try:
            with self._lock:
                self._socket.send_multipart(encode_command(command), flags=zmq.NOBLOCK)
            self._logger.debug_event(
                Event.External.PUBLISHED,
                component=Component.EXTERNAL_FORWARDING,
                event_type=event_type,
            )
        except zmq.ZMQError as exc:
            self._logger.warning_event(
                Event.External.PUBLISH_FAILED,
                component=Component.EXTERNAL_FORWARDING,
                event_type=event_type,
                error=str(exc),
            )

    def close(self) -> None:
        """Closes the socket. Raises LINGER from 0 to a short bounded window
        first -- publish() only enqueues onto ZMQ's async I/O thread, so a
        publish() immediately followed by close() (e.g. App.stop()'s
        EndpointStopped, the very last event this socket ever sends) would
        otherwise have its message silently dropped by the LINGER=0 used for
        every other fire-and-forget send during normal operation, when
        nothing calls close() right after."""
        self._socket.setsockopt(zmq.LINGER, 200)
        self._socket.close()
