from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict


@dataclass(frozen=True)
class Event:
    """A lifecycle/completion notification, independent of any transport.

    ``payload`` must stay primitives/ids only — never raw bytes or large
    data (that goes through storage-by-reference instead, see
    ``core.results.envelope.FunctionResult``). ``timestamp`` is supplied by
    the caller rather than stamped internally, matching ``PeerInfo.last_seen``,
    so tests stay deterministic without mocking the clock.
    """

    event_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


class EventBus(ABC):
    """Transport-agnostic publish/subscribe contract.

    Lifecycle code calls ``emit`` without knowing whether that ends up on a
    ZMQ PUB socket, a log line, or nothing at all — letting tests use a
    trivial in-memory fake with zero networking.
    """

    @abstractmethod
    def emit(self, event: Event) -> None: ...

    @abstractmethod
    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None: ...
