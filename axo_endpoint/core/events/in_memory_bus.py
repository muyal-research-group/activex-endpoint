from __future__ import annotations

from typing import Callable, Dict, List, Optional

from axo_endpoint.core.events.bus import Event, EventBus

ErrorHandler = Callable[[str, BaseException], None]


class InMemoryEventBus(EventBus):
    """Dict-backed ``EventBus``: synchronous, in-process dispatch.

    A subscriber that raises must not prevent other subscribers (for the
    same or a different ``event_type``) from being called — one bad handler
    can't break emission for everyone else. Exceptions are reported through
    the optional ``on_handler_error`` callback rather than a hard dependency
    on a particular logger, keeping this module free of real I/O; ``service/``
    wiring can pass ``Log.error_event`` (or similar) here later.
    """

    def __init__(self, on_handler_error: Optional[ErrorHandler] = None) -> None:
        self._subscribers: Dict[str, List[Callable[[Event], None]]] = {}
        self._on_handler_error = on_handler_error

    def emit(self, event: Event) -> None:
        for handler in list(self._subscribers.get(event.event_type, [])):
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 - isolate subscribers from each other
                if self._on_handler_error is not None:
                    self._on_handler_error(event.event_type, exc)

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)
