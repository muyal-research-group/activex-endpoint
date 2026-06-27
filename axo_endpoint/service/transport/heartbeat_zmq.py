from __future__ import annotations

import json
import threading
import time
from typing import Callable, Dict, List, Optional

import zmq

from axo_endpoint.core.network.heartbeat import HeartbeatPublisher, HeartbeatSubscriber, PeerInfo

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
    ) -> None:
        """Connects to one or more peers to start receiving their heartbeats."""
        self._context = context or zmq.Context.instance()
        self._socket = self._context.socket(zmq.SUB)
        self._socket.setsockopt(zmq.SUBSCRIBE, HB_TOPIC)
        for address in connect_addresses:
            self._socket.connect(address)
        self._socket.setsockopt(zmq.RCVTIMEO, 200)  # ms -- lets the recv loop notice stop()

        self._now_fn = now_fn
        self._peers: Dict[str, PeerInfo] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts listening for heartbeats in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stops listening and closes the socket."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._socket.close()

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
            return
        _topic, peer_id_b, service_name_b, rpc_uri_b, metrics_b = frames
        try:
            metrics = json.loads(metrics_b.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        self.on_heartbeat(
            PeerInfo(
                peer_id=peer_id_b.decode("utf-8"),
                service_name=service_name_b.decode("utf-8"),
                rpc_uri=rpc_uri_b.decode("utf-8"),
                metrics=metrics,
                last_seen=self._now_fn(),
            )
        )

    def on_heartbeat(self, info: PeerInfo) -> None:
        """Records that a heartbeat was received from a peer."""
        with self._lock:
            self._peers[info.peer_id] = info

    def evict_stale(self, ttl_seconds: float, now: float) -> List[str]:
        """Removes peers that haven't sent a heartbeat in too long, and returns their ids."""
        with self._lock:
            stale_ids = [pid for pid, info in self._peers.items() if now - info.last_seen > ttl_seconds]
            for pid in stale_ids:
                self._peers.pop(pid, None)
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
