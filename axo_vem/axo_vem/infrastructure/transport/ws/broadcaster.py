from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket


class Broadcaster:
    """Generic pub/sub fan-out to connected WebSocket clients, grouped by an
    arbitrary string topic (e.g. "buckets", "endpoints", "endpoints:<id>").
    Shared across every WS-backed feature (bucket status pushes, endpoint
    stats) rather than each route reimplementing its own connection
    bookkeeping -- see the plan this was built from.

    Connection add/remove and actual message delivery all happen on
    whichever asyncio event loop FastAPI/uvicorn is running on (every
    WebSocket route handler runs there), so ``_topics`` is never touched
    from more than one thread and needs no lock. The one exception is
    ``broadcast()`` itself: callers on a different thread (the Kurrent
    subscriber's background thread, a future stats-polling thread) reach
    the event loop via ``asyncio.run_coroutine_threadsafe`` instead of
    calling straight into a coroutine that was never scheduled there.
    """

    def __init__(self) -> None:
        self._topics: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once, from a FastAPI startup hook running on the loop
        uvicorn actually serves requests on -- the only point in the
        process lifecycle that loop is guaranteed to exist and be running."""
        self._loop = loop

    def register(self, topic: str, websocket: WebSocket) -> None:
        self._topics[topic].add(websocket)

    def unregister(self, topic: str, websocket: WebSocket) -> None:
        self._topics[topic].discard(websocket)

    def broadcast(self, topic: str, message: Dict[str, Any]) -> None:
        """Thread-safe: safe to call from any thread, including one with no
        event loop of its own. A no-op before bind_loop() has run or if
        nothing is currently subscribed to ``topic`` -- callers don't need
        to check either condition themselves."""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._deliver(topic, message), self._loop)

    async def _deliver(self, topic: str, message: Dict[str, Any]) -> None:
        dead = []
        for websocket in list(self._topics.get(topic, ())):
            try:
                await websocket.send_json(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self._topics[topic].discard(websocket)
