from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union

from pymongo.collection import Collection

from axo_shared import wire
from axo_shared.protocol import Command

from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.domain.events.stream_naming import stream_name_for
from axo_vem.infrastructure.transport.zmq_command.endpoint_client import resolve_rpc_uri, send_command
from axo_vem.log import DumbLogger, Log
from axo_vem.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


def _parse_created_at(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class EndpointLivenessWorker:
    """Background daemon thread (same sleep-loop pattern as
    ActivityRetentionWorker/EndpointStatsPoller/KurrentSubscriber) that
    detects endpoint nodes that have gone dark and appends
    EndpointUnreachable/EndpointRecovered events accordingly -- both real
    Kurrent-appended events (audit parity with EndpointStarted/Stopped),
    not a bare Mongo write.

    Two-phase per tick:
    1. Passive: every `running` doc whose created_at (doubling as
       "last seen" -- see domain/compute/endpoint.py's last_seen_at
       docstring) is older than stale_after_seconds becomes an
       active-check candidate.
    2. Active: PING each candidate directly (same Command/send_command/
       resolve_rpc_uri pattern as application/compute/register_function.py
       etc.). Failure -> EndpointUnreachable. Every `unreachable` doc is
       *also* PINGed every tick, unconditionally (no staleness gate --
       it's already down) -- success -> EndpointRecovered. A same-state
       result is a no-op (idempotent).

    Queries the raw `endpoints` Collection directly, like
    EndpointStatsPoller, rather than through EndpointRepository -- the
    projector is the only writer that needs the aggregate abstraction;
    this worker only ever reads to decide who to ping.
    """

    def __init__(
        self,
        endpoints: Collection,
        event_publisher: EventPublisher,
        stale_after_seconds: float,
        tick_seconds: float = 30.0,
        ping_timeout_seconds: float = 3.0,
        logger: _Logger = None,
    ) -> None:
        self._endpoints = endpoints
        self._event_publisher = event_publisher
        self._stale_after_seconds = stale_after_seconds
        self._tick_seconds = tick_seconds
        self._ping_timeout_seconds = ping_timeout_seconds
        self._logger: _Logger = logger or DumbLogger()
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def run_forever(self) -> None:
        while not self._stopped:
            self.tick()
            time.sleep(self._tick_seconds)

    def tick(self) -> None:
        try:
            now = datetime.now(timezone.utc)
            stale_cutoff = now - timedelta(seconds=self._stale_after_seconds)

            for doc in self._endpoints.find({"status": "running"}):
                last_seen = _parse_created_at(doc.get("created_at"))
                if last_seen is None or last_seen > stale_cutoff:
                    continue  # still within the heartbeat window
                self._check(doc, currently_unreachable=False)

            for doc in self._endpoints.find({"status": "unreachable"}):
                self._check(doc, currently_unreachable=True)
        except Exception as exc:
            self._logger.error_event(
                Event.EndpointLiveness.TICK_FAILED,
                component=Component.ENDPOINT_LIVENESS,
                error=str(exc),
            )

    def _check(self, doc: Dict[str, Any], currently_unreachable: bool) -> None:
        endpoint_id = doc["_id"]
        reachable = self._ping(doc)
        if reachable is None:
            return  # no router_bind known -- can't probe, don't guess

        if currently_unreachable and reachable:
            event = models.EndpointRecovered(endpoint_id=endpoint_id)
            self._publish(endpoint_id, models.ENDPOINT_RECOVERED, event)
        elif not currently_unreachable and not reachable:
            event = models.EndpointUnreachable(endpoint_id=endpoint_id, last_seen_at=doc.get("created_at"))
            self._publish(endpoint_id, models.ENDPOINT_UNREACHABLE, event)
        # else: same-state result, nothing to do (idempotent)

    def _ping(self, doc: Dict[str, Any]) -> Optional[bool]:
        router_bind = doc.get("router_bind")
        if not router_bind:
            self._logger.warning_event(
                Event.EndpointLiveness.NO_ROUTER_BIND,
                component=Component.ENDPOINT_LIVENESS,
                endpoint_id=doc["_id"],
            )
            return None
        rpc_uri = resolve_rpc_uri(router_bind, doc["_id"])
        command = Command(operation=wire.PING, content_type="application/json", envelope={}, payload=b"")
        result = send_command(rpc_uri, command, self._ping_timeout_seconds)
        return result.is_ok and result.unwrap().ok

    def _publish(self, endpoint_id: str, event_type: str, event: Any) -> None:
        data = event.model_dump(mode="json")
        stream = stream_name_for(event_type, endpoint_id, data)
        self._event_publisher.append_to_stream(stream, event_type, data)
        self._logger.info_event(
            Event.EndpointLiveness.STATUS_CHANGED,
            component=Component.ENDPOINT_LIVENESS,
            endpoint_id=endpoint_id,
            event_type=event_type,
        )
