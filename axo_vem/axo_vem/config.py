from __future__ import annotations

import logging
import os
from typing import List, Optional


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _list(name: str, default: str) -> List[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).lower() in {"1", "true", "yes", "on"}


def _level(name: str, default: str) -> int:
    return getattr(logging, os.environ.get(name, default).upper(), getattr(logging, default))


def _indent(name: str) -> Optional[int]:
    raw = os.environ.get(name, "0")
    val = int(raw) if raw.isdigit() else 0
    return val if val > 0 else None


class Config:
    """Holds all AXO_VEM_* settings. The single place that reads os.environ."""

    def __init__(self) -> None:
        # ZMQ ingestion (node -> API, internal only)
        self.AXO_VEM_ROUTER_BIND: str = os.environ.get(
            "AXO_VEM_ROUTER_BIND", "tcp://0.0.0.0:6000"
        )

        # Outbound commands (API -> node, e.g. VIRTUAL_ENV_ASSIGN)
        self.AXO_VEM_ENDPOINT_COMMAND_TIMEOUT_SECONDS: float = float(
            os.environ.get("AXO_VEM_ENDPOINT_COMMAND_TIMEOUT_SECONDS", "10.0")
        )

        # HTTP (external, the only exposed surface)
        self.AXO_VEM_HTTP_HOST: str = os.environ.get(
            "AXO_VEM_HTTP_HOST", "0.0.0.0"
        )
        self.AXO_VEM_HTTP_PORT: int = _int("AXO_VEM_HTTP_PORT", 8080)

        # CORS (browser-facing frontend origins allowed to call the HTTP API
        # directly -- e.g. axo-ui's dev server). Empty means no CORSMiddleware
        # is installed at all, not "allow nothing".
        self.AXO_VEM_CORS_ORIGINS: List[str] = _list(
            "AXO_VEM_CORS_ORIGINS", "*"
        )

        # Kurrent (write side / source of truth)
        self.AXO_VEM_KURRENT_URI: str = os.environ.get(
            "AXO_VEM_KURRENT_URI", "esdb://localhost:2113?tls=false"
        )

        # MongoDB (read side / materialized view)
        self.AXO_VEM_MONGO_URI: str = os.environ.get(
            "AXO_VEM_MONGO_URI", "mongodb://localhost:27017"
        )
        self.AXO_VEM_MONGO_DB_NAME: str = os.environ.get(
            "AXO_VEM_MONGO_DB_NAME", "axo_vem"
        )

        # Retry/backoff for Mongo/Kurrent connection attempts -- shared by the
        # eager startup probe (server.py), KurrentSubscriber's reconnect loop,
        # and IngestionRouterServer's append retry (see infrastructure/resilience/retry.py).
        self.AXO_VEM_DB_CONNECT_MAX_ATTEMPTS: int = _int(
            "AXO_VEM_DB_CONNECT_MAX_ATTEMPTS", 10
        )
        self.AXO_VEM_DB_CONNECT_BASE_DELAY_SECONDS: float = float(
            os.environ.get("AXO_VEM_DB_CONNECT_BASE_DELAY_SECONDS", "1.0")
        )
        self.AXO_VEM_DB_CONNECT_MAX_DELAY_SECONDS: float = float(
            os.environ.get("AXO_VEM_DB_CONNECT_MAX_DELAY_SECONDS", "30.0")
        )
        # Backstop for a KurrentSubscriber subscription that goes silently
        # idle (no exception, no data) after a network disruption -- see
        # infrastructure/database/kurrent/subscriber.py's watchdog.
        self.AXO_VEM_PROJECTOR_STALE_AFTER_SECONDS: float = float(
            os.environ.get("AXO_VEM_PROJECTOR_STALE_AFTER_SECONDS", "60.0")
        )

        # Xolo (identity / access control -- see auth/dependency.py)
        self.AXO_VEM_XOLO_URI: str = os.environ.get(
            "AXO_VEM_XOLO_URI", "http://localhost:10000/api/v4"
        )
        self.AXO_VEM_XOLO_API_KEY: str = os.environ.get("AXO_VEM_XOLO_API_KEY", "")
        self.AXO_VEM_XOLO_ACCOUNT_ID: str = os.environ.get("AXO_VEM_XOLO_ACCOUNT_ID", "")

        # Node deployment (launching new axo_endpoint node containers via
        # the shared axo_shared.container.ContainerSpawner -- see
        # application/nodes/launch_endpoint_node.py)
        self.AXO_VEM_NODE_IMAGE: str = os.environ.get(
            "AXO_VEM_NODE_IMAGE", "axo-endpoint:local"
        )
        self.AXO_VEM_NODE_NETWORK: str = os.environ.get(
            "AXO_VEM_NODE_NETWORK", "axo-net"
        )
        self.AXO_VEM_DOCKER_MODE: str = os.environ.get(
            "AXO_VEM_DOCKER_MODE", "docker"
        )
        # The resolvable address a newly-launched node should use for its own
        # AXO_ENDPOINT_API_URI -- this node's own bind address isn't
        # connectable from another container (same resolvability gap as a
        # peer's heartbeat rpc_uri, see root CLAUDE.md), so it's a separate,
        # explicitly-configured value rather than derived from ROUTER_BIND.
        self.AXO_VEM_NODE_API_URI: str = os.environ.get(
            "AXO_VEM_NODE_API_URI", "tcp://axo-vem:6000"
        )
        # How often EndpointStatsPoller polls Docker container stats for
        # every known endpoint and broadcasts them over /ws/endpoints --
        # see infrastructure/container/endpoint_stats_poller.py.
        self.AXO_VEM_STATS_POLL_INTERVAL_SECONDS: float = float(
            os.environ.get("AXO_VEM_STATS_POLL_INTERVAL_SECONDS", "3.0")
        )

        # unified_activity retention -- a fixed system-wide ceiling,
        # independent of any user's own activity_window_minutes display
        # preference (see infrastructure/transport/api/controllers/history.py).
        # ActivityRetentionWorker hard-deletes rows older than this on its
        # own tick cadence -- see application/activity/retention_worker.py.
        self.AXO_VEM_ACTIVITY_RETENTION_HOURS: float = float(
            os.environ.get("AXO_VEM_ACTIVITY_RETENTION_HOURS", "1.0")
        )
        self.AXO_VEM_ACTIVITY_RETENTION_TICK_SECONDS: float = float(
            os.environ.get("AXO_VEM_ACTIVITY_RETENTION_TICK_SECONDS", "300.0")
        )

        # Endpoint liveness detection -- EndpointLivenessWorker (see
        # infrastructure/transport/zmq_command/endpoint_liveness_worker.py).
        # X: fixed, system-wide staleness threshold -- no per-user override,
        # the worker has no request-scoped current user to resolve one
        # against.
        self.AXO_VEM_ENDPOINT_STALE_AFTER_SECONDS: float = float(
            os.environ.get("AXO_VEM_ENDPOINT_STALE_AFTER_SECONDS", "90.0")
        )
        self.AXO_VEM_ENDPOINT_LIVENESS_TICK_SECONDS: float = float(
            os.environ.get("AXO_VEM_ENDPOINT_LIVENESS_TICK_SECONDS", "30.0")
        )
        self.AXO_VEM_ENDPOINT_PING_TIMEOUT_SECONDS: float = float(
            os.environ.get("AXO_VEM_ENDPOINT_PING_TIMEOUT_SECONDS", "3.0")
        )
        # Y's fallback default (see Preferences.endpoint_purge_eligible_after_minutes,
        # axo_shared/axo_shared/events/models.py) -- resolved per-request by
        # _purge_eligible_after_for() in infrastructure/transport/api/controllers/
        # endpoints.py when the viewing user has no profile / no explicit
        # override, mirroring history.py's _since_for -- except sourced from
        # this env var rather than a hardcoded Python constant.
        self.AXO_VEM_ENDPOINT_PURGE_ELIGIBLE_AFTER_MINUTES: int = _int(
            "AXO_VEM_ENDPOINT_PURGE_ELIGIBLE_AFTER_MINUTES", 60
        )

        # Logging
        self.AXO_VEM_LOG_LEVEL: int = _level("AXO_VEM_LOG_LEVEL", "DEBUG")
        self.AXO_VEM_LOG_DISABLED: bool = _bool("AXO_VEM_LOG_DISABLED", "false")
        self.AXO_VEM_LOG_TO_FILE: bool = _bool("AXO_VEM_LOG_TO_FILE", "false")
        self.AXO_VEM_LOG_PATH: str = os.environ.get(
            "AXO_VEM_LOG_PATH", ".axo_vem/log"
        )
        self.AXO_VEM_LOG_FILENAME: str = os.environ.get(
            "AXO_VEM_LOG_FILENAME", "axo_vem"
        )
        self.AXO_VEM_LOG_OUTPUT_PATH: Optional[str] = os.environ.get(
            "AXO_VEM_LOG_OUTPUT_PATH"
        )
        self.AXO_VEM_LOG_ERROR_OUTPUT_PATH: Optional[str] = os.environ.get(
            "AXO_VEM_LOG_ERROR_OUTPUT_PATH"
        )
        self.AXO_VEM_LOG_CONSOLE_LEVEL: int = _level(
            "AXO_VEM_LOG_CONSOLE_LEVEL", "DEBUG"
        )
        self.AXO_VEM_LOG_FILE_LEVEL: int = _level(
            "AXO_VEM_LOG_FILE_LEVEL", "DEBUG"
        )
        self.AXO_VEM_LOG_ERROR_FILE: bool = _bool(
            "AXO_VEM_LOG_ERROR_FILE", "false"
        )
        self.AXO_VEM_LOG_ROTATION_WHEN: str = os.environ.get(
            "AXO_VEM_LOG_ROTATION_WHEN", "midnight"
        )
        self.AXO_VEM_LOG_ROTATION_INTERVAL: int = _int(
            "AXO_VEM_LOG_ROTATION_INTERVAL", 1
        )
        self.AXO_VEM_LOG_JSON_INDENT: Optional[int] = _indent(
            "AXO_VEM_LOG_JSON_INDENT"
        )
        self.AXO_VEM_LOG_USE_RICH: bool = _bool("AXO_VEM_LOG_USE_RICH", "false")
        self.AXO_VEM_LOG_COLORIZE: bool = _bool("AXO_VEM_LOG_COLORIZE", "true")

    def update(self, **kwargs) -> None:
        """Overrides one or more settings after creation. Unknown setting names are ignored."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
