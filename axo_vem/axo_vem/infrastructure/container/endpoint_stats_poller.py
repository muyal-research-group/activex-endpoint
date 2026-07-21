from __future__ import annotations

import time
from typing import Union

from pymongo.collection import Collection

from axo_shared.container.spawner import ContainerSpawner
from axo_shared.runtime.spec import ContainerMode

from axo_vem.infrastructure.transport.ws.broadcaster import Broadcaster
from axo_vem.log import DumbLogger, Log
from axo_vem.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]

WS_TOPIC_ALL = "endpoints"


def _scoped_topic(endpoint_id: str) -> str:
    return f"endpoints:{endpoint_id}"


class EndpointStatsPoller:
    """Background daemon thread (same sleep-loop pattern as
    KurrentSubscriber and the ZMQ ingestion router in server.py) polling
    Docker container stats for every endpoint this API knows about,
    broadcasting one message per endpoint per tick to both the fleet-wide
    "endpoints" topic and that endpoint's own "endpoints:<id>" topic --
    /ws/endpoints and /ws/endpoints/{endpoint_id} are just two routes
    subscribing to different slices of the same feed.

    Only reaches actual container stats for endpoints this API itself
    launched (ContainerSpawner.get() resolves a container by name ==
    endpoint_id, true only for LaunchEndpointNodeUseCase's own spawns --
    see stop_endpoint_node.py's identical limitation for stop/restart). A
    docker-compose-managed node's container name won't match its
    endpoint_id, so it gets an ``available: False`` message instead of
    being silently skipped -- the UI can render "stats unavailable"
    explicitly rather than just showing nothing.
    """

    def __init__(
        self,
        endpoints: Collection,
        spawner: ContainerSpawner,
        mode: ContainerMode,
        broadcaster: Broadcaster,
        interval_seconds: float = 3.0,
        logger: _Logger = None,
    ) -> None:
        self._endpoints = endpoints
        self._spawner = spawner
        self._mode = mode
        self._broadcaster = broadcaster
        self._interval_seconds = interval_seconds
        self._logger: _Logger = logger or DumbLogger()
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def run_forever(self) -> None:
        while not self._stopped:
            self.tick()
            time.sleep(self._interval_seconds)

    def tick(self) -> None:
        for doc in self._endpoints.find():
            try:
                message = self._message_for(doc["_id"])
            except Exception as exc:
                self._logger.error_event(
                    Event.StatsPoller.TICK_FAILED,
                    component=Component.STATS_POLLER,
                    endpoint_id=doc.get("_id"),
                    error=str(exc),
                )
                continue
            self._broadcaster.broadcast(WS_TOPIC_ALL, message)
            self._broadcaster.broadcast(_scoped_topic(message["endpoint_id"]), message)

    def _message_for(self, endpoint_id: str) -> dict:
        handle = self._spawner.get(self._mode, endpoint_id)
        if handle is None:
            return {"endpoint_id": endpoint_id, "available": False}

        result = self._spawner.stats(handle)
        if result.is_err:
            return {"endpoint_id": endpoint_id, "available": False}

        stats = result.unwrap()
        return {
            "endpoint_id": endpoint_id,
            "available": True,
            "cpu_percent": stats.cpu_percent,
            "memory_usage": stats.memory_usage,
            "memory_limit": stats.memory_limit,
            "network_rx": stats.network_rx,
            "network_tx": stats.network_tx,
        }
