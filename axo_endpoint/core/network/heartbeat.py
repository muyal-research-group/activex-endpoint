from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PeerInfo:
    """A peer's last known status: when it was last seen and how healthy it is."""

    peer_id: str
    service_name: str
    rpc_uri: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    last_seen: float = 0.0


class HeartbeatPublisher(ABC):
    """Sends out this endpoint's own status to other peers."""

    @abstractmethod
    def publish(self, info: PeerInfo) -> None:
        """Sends one status update to other peers."""


class HeartbeatSubscriber(ABC):
    """Keeps track of which peers are alive, based on their heartbeats."""

    @abstractmethod
    def on_heartbeat(self, info: PeerInfo) -> None:
        """Records that a heartbeat was received from a peer."""

    @abstractmethod
    def evict_stale(self, ttl_seconds: float, now: float) -> List[str]:
        """Removes peers that haven't sent a heartbeat in too long, and returns their ids."""

    @abstractmethod
    def get_peer(self, peer_id: str) -> Optional[PeerInfo]:
        """Looks up one peer by id."""

    @abstractmethod
    def list_peers(self) -> List[PeerInfo]:
        """Lists all known peers."""
