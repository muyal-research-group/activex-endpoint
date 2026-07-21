from __future__ import annotations

import json
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Union

import zmq

from axo_endpoint.core.network.heartbeat import HeartbeatPublisher, HeartbeatSubscriber, PeerInfo
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]

# Topic name used for heartbeat messages.
HB_TOPIC = b"AXO_ENDPOINT.HEARTBEAT"


class ZmqHeartbeatPublisher(HeartbeatPublisher):
    """Sends this endpoint's heartbeat to other peers."""

    def __init__(self, bind_address: str, context: Optional["zmq.Context"] = None) -> None:
        """Binds a socket so heartbeats can be published."""
        self._context = context or zmq.Context.instance()
        self._socket = self._context.socket(zmq.PUB)
        self._socket.bind(bind_address)

    def publish(self, info: PeerInfo) -> None:
        """Sends one heartbeat message to anyone listening."""
        frames = [
            HB_TOPIC,
            info.peer_id.encode("utf-8"),
            info.service_name.encode("utf-8"),
            info.rpc_uri.encode("utf-8"),
            json.dumps(info.metrics, default=str).encode("utf-8"),
        ]
        self._socket.send_multipart(frames)

    def close(self) -> None:
        """Closes the socket."""
        self._socket.close()


class ZmqHeartbeatSubscriber(HeartbeatSubscriber):
    """Listens for heartbeat messages from other endpoints and remembers which ones are alive."""

    def __init__(
        self,
        connect_addresses: List[str],
        context: Optional["zmq.Context"] = None,
        now_fn: Callable[[], float] = time.time,
        logger: _Logger = None,
        on_new_peer: Optional[Callable[[PeerInfo], None]] = None,
    ) -> None:
        """Connects to one or more peers to start receiving their heartbeats."""
        self._context = context or zmq.Context.instance()
        self._socket = self._context.socket(zmq.SUB)
        self._socket.setsockopt(zmq.SUBSCRIBE, HB_TOPIC)
        self._connected: Set[str] = set()
        for address in connect_addresses:
            self._socket.connect(address)
            self._connected.add(address)
        self._socket.setsockopt(zmq.RCVTIMEO, 200)  # ms -- lets the recv loop notice stop()

        self._now_fn = now_fn
        self._peers: Dict[str, PeerInfo] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._logger: _Logger = logger or DumbLogger()
        self._connect_addresses = connect_addresses
        self._on_new_peer = on_new_peer

    def start(self) -> None:
        """Starts listening for heartbeats in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._logger.info_event(
            event             = Event.Heartbeat.SUBSCRIBER_STARTED,
            component         = Component.HEARTBEAT,
            connect_addresses = self._connect_addresses,
            peer_count        = len(self._connect_addresses),
        )

    def connect(self, address: str) -> None:
        """Dynamically subscribes to an additional peer PUB address (idempotent)."""
        with self._lock:
            if address in self._connected:
                return
            self._connected.add(address)
        self._socket.connect(address)

    def stop(self) -> None:
        """Stops listening and closes the socket."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._socket.close()
        self._logger.info_event(
            Event.Heartbeat.SUBSCRIBER_STOPPED,
            component=Component.HEARTBEAT,
        )

    def _run(self) -> None:
        """Repeatedly waits for and processes incoming heartbeat messages."""
        while self._running:
            try:
                frames = self._socket.recv_multipart()
            except zmq.Again:
                continue
            except zmq.ZMQError:
                break
            self._handle_frames(frames)

    def _handle_frames(self, frames: List[bytes]) -> None:
        """Decodes one incoming heartbeat message and records it."""
        if len(frames) != 5:
            self._logger.debug_event(
                Event.Heartbeat.FRAME_DROPPED,
                component   = Component.HEARTBEAT,
                frame_count = len(frames),
            )
            return
        _topic, peer_id_b, service_name_b, rpc_uri_b, metrics_b = frames
        try:
            metrics = json.loads(metrics_b.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._logger.debug_event(
                Event.Heartbeat.DECODE_ERROR,
                component = Component.HEARTBEAT,
                peer_id   = peer_id_b.decode("utf-8", errors="replace"),
            )
            return

        now = self._now_fn()
        sent_at = metrics.pop("__sent_at__", None)
        pub_bind = metrics.pop("__pub_bind__", "")
        latency_ms = round((now - sent_at) * 1000, 2) if sent_at is not None else 0.0

        self.on_heartbeat(
            PeerInfo(
                peer_id      = peer_id_b.decode("utf-8"),
                service_name = service_name_b.decode("utf-8"),
                rpc_uri      = rpc_uri_b.decode("utf-8"),
                metrics      = metrics,
                last_seen    = now,
                pub_bind     = pub_bind,
                latency_ms   = latency_ms,
            )
        )

    def on_heartbeat(self, info: PeerInfo) -> None:
        """Records that a heartbeat was received from a peer."""
        with self._lock:
            is_new = info.peer_id not in self._peers
            self._peers[info.peer_id] = info

        if is_new:
            self._logger.info_event(
                Event.Peer.DISCOVERED,
                component=Component.HEARTBEAT,
                peer_id=info.peer_id,
                service_name=info.service_name,
                rpc_uri=info.rpc_uri,
                pub_bind=info.pub_bind,
                latency_ms=info.latency_ms,
            )
            if self._on_new_peer is not None:
                self._on_new_peer(info)
        else:
            self._logger.debug_event(
                Event.Peer.HEARTBEAT,
                component=Component.HEARTBEAT,
                peer_id=info.peer_id,
                latency_ms=info.latency_ms,
                metrics=info.metrics,
            )

    def evict_stale(self, ttl_seconds: float, now: float) -> List[str]:
        """Removes peers that haven't sent a heartbeat in too long, and returns their ids."""
        with self._lock:
            stale_ids = [pid for pid, info in self._peers.items() if now - info.last_seen > ttl_seconds]
            for pid in stale_ids:
                self._peers.pop(pid, None)

        for pid in stale_ids:
            self._logger.info_event(
                Event.Peer.EVICTED,
                component=Component.HEARTBEAT,
                peer_id=pid,
                reason="ttl_expired",
                ttl_seconds=ttl_seconds,
            )
        return stale_ids

    def get_peer(self, peer_id: str) -> Optional[PeerInfo]:
        """Looks up one peer by id."""
        with self._lock:
            return self._peers.get(peer_id)

    def list_peers(self) -> List[PeerInfo]:
        """Lists all known peers."""
        with self._lock:
            return list(self._peers.values())


def run_heartbeat_gc(
    subscriber: HeartbeatSubscriber,
    ttl_seconds: float,
    interval_seconds: float,
    stop_event: threading.Event,
    now_fn: Callable[[], float] = time.time,
) -> None:
    """Runs in the background and removes peers that haven't sent a heartbeat in too long."""
    while not stop_event.is_set():
        subscriber.evict_stale(ttl_seconds, now_fn())
        stop_event.wait(interval_seconds)
