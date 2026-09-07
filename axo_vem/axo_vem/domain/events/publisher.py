from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class EventPublisher(ABC):
    """Appends one taxonomy event to its Kurrent stream. Unifies the two
    write paths that exist in this service: node-originated events arriving
    over ZMQ (infrastructure/transport/zmq_ingestion) and UserProfile/
    VirtualEnvironment events appended directly from HTTP request handlers
    (application/identity, application/workspace) -- both depend on this
    same abstract port rather than each knowing about kurrentdbclient."""

    @abstractmethod
    def append_to_stream(self, stream_name: str, event_type: str, data: Dict[str, Any]) -> None: ...
