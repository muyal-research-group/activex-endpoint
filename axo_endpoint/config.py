from __future__ import annotations

import logging
import os
from typing import List, Optional


def _bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _level(name: str, default: str) -> int:
    return getattr(logging, os.environ.get(name, default).upper(), getattr(logging, default))


def _indent(name: str) -> Optional[int]:
    raw = os.environ.get(name, "0")
    val = int(raw) if raw.isdigit() else 0
    return val if val > 0 else None


class Config:
    """Holds all AXO_ENDPOINT_* settings. The single place that reads os.environ."""

    def __init__(self) -> None:
        # Identity
        self.AXO_ENDPOINT_ID: str = os.environ.get("AXO_ENDPOINT_ID", "axo-endpoint-0")

        # Transport
        self.AXO_ENDPOINT_ROUTER_BIND: str = os.environ.get(
            "AXO_ENDPOINT_ROUTER_BIND", "tcp://0.0.0.0:5555"
        )
        self.AXO_ENDPOINT_PUB_BIND: str = os.environ.get(
            "AXO_ENDPOINT_PUB_BIND", "tcp://0.0.0.0:5556"
        )
        self.AXO_ENDPOINT_SUB_CONNECT: List[str] = [
            s for s in os.environ.get("AXO_ENDPOINT_SUB_CONNECT", "").split(",") if s
        ]

        # Heartbeat
        self.AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS", "5.0")
        )
        self.AXO_ENDPOINT_HEARTBEAT_TTL_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_HEARTBEAT_TTL_SECONDS", "30.0")
        )

        # Queue / dispatcher
        self.AXO_ENDPOINT_QUEUE_MAX_DEPTH: int = _int("AXO_ENDPOINT_QUEUE_MAX_DEPTH", 1000)
        self.AXO_ENDPOINT_QUEUE_WORKERS: int = _int("AXO_ENDPOINT_QUEUE_WORKERS", 4)

        # Process runtime: idle/recycle
        self.AXO_ENDPOINT_WORKER_IDLE_TTL_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_WORKER_IDLE_TTL_SECONDS", "300.0")
        )
        self.AXO_ENDPOINT_WORKER_GC_INTERVAL_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_WORKER_GC_INTERVAL_SECONDS", "30.0")
        )
        self.AXO_ENDPOINT_WORKER_MAX_INVOCATIONS: int = _int(
            "AXO_ENDPOINT_WORKER_MAX_INVOCATIONS", 0
        )  # 0 = unlimited

        # Process runtime: rlimits
        self.AXO_ENDPOINT_WORKER_RLIMIT_AS_BYTES: int = _int(
            "AXO_ENDPOINT_WORKER_RLIMIT_AS_BYTES", 512 * 1024 * 1024
        )
        self.AXO_ENDPOINT_WORKER_RLIMIT_CPU_SECONDS: int = _int(
            "AXO_ENDPOINT_WORKER_RLIMIT_CPU_SECONDS", 30
        )

        # Local testing mode — peer addresses use localhost instead of peer_id as host
        self.AXO_ENDPOINT_LOCAL_MODE: bool = _bool("AXO_ENDPOINT_LOCAL_MODE", "false")

        # Consensus / replication
        self.AXO_ENDPOINT_CONSENSUS_REPLICATION_IDLE_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_CONSENSUS_REPLICATION_IDLE_SECONDS", "2.0")
        )
        self.AXO_ENDPOINT_CONSENSUS_REPLICATION_MAX_DIRTY: int = _int(
            "AXO_ENDPOINT_CONSENSUS_REPLICATION_MAX_DIRTY", 50
        )
        self.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS", "3.0")
        )
        self.AXO_ENDPOINT_CONSENSUS_BLOB_CHUNK_BYTES: int = _int(
            "AXO_ENDPOINT_CONSENSUS_BLOB_CHUNK_BYTES", 262144  # 256 KiB
        )
        self.AXO_ENDPOINT_CONSENSUS_BLOB_RATE_LIMIT_BYTES_PER_SECOND: int = _int(
            "AXO_ENDPOINT_CONSENSUS_BLOB_RATE_LIMIT_BYTES_PER_SECOND", 1048576  # 1 MiB/s
        )
        self.AXO_ENDPOINT_CONSENSUS_BLOB_TICK_INTERVAL_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_CONSENSUS_BLOB_TICK_INTERVAL_SECONDS", "0.1")
        )
        self.AXO_ENDPOINT_BLOB_REPLICATION_IDLE_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_BLOB_REPLICATION_IDLE_SECONDS", "60.0")
        )
        self.AXO_ENDPOINT_BLOB_REPLICATION_ENABLED_KINDS: List[str] = [
            s for s in os.environ.get("AXO_ENDPOINT_BLOB_REPLICATION_ENABLED_KINDS", "fs").split(",") if s
        ]
        self.AXO_ENDPOINT_BLOB_REPLICATION_RECHECK_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_BLOB_REPLICATION_RECHECK_SECONDS", "300.0")
        )

        # Activity tracking
        self.AXO_ENDPOINT_ACTIVITY_LOG_MAX_ENTRIES: int = _int(
            "AXO_ENDPOINT_ACTIVITY_LOG_MAX_ENTRIES", 10000
        )

        # Scratch directories
        self.AXO_ENDPOINT_SCRATCH_ROOT: str = os.environ.get(
            "AXO_ENDPOINT_SCRATCH_ROOT", "/tmp/axo_endpoint/scratch"
        )
        self.AXO_ENDPOINT_SCRATCH_GC_INTERVAL_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_SCRATCH_GC_INTERVAL_SECONDS", "60.0")
        )

        # Data IO
        self.AXO_ENDPOINT_DATAIO_FS_ROOT: str = os.environ.get(
            "AXO_ENDPOINT_DATAIO_FS_ROOT", "/tmp/axo_endpoint/dataio"
        )
        self.AXO_ENDPOINT_DATAIO_TIMEOUT_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_DATAIO_TIMEOUT_SECONDS", "30.0")
        )

        # Logging
        self.AXO_ENDPOINT_LOG_LEVEL: int = _level("AXO_ENDPOINT_LOG_LEVEL", "DEBUG")
        self.AXO_ENDPOINT_LOG_DISABLED: bool = _bool("AXO_ENDPOINT_LOG_DISABLED", "false")
        self.AXO_ENDPOINT_LOG_TO_FILE: bool = _bool("AXO_ENDPOINT_LOG_TO_FILE", "false")
        self.AXO_ENDPOINT_LOG_PATH: str = os.environ.get(
            "AXO_ENDPOINT_LOG_PATH", ".axo_endpoint/log"
        )
        self.AXO_ENDPOINT_LOG_FILENAME: str = os.environ.get(
            "AXO_ENDPOINT_LOG_FILENAME", "axo_endpoint"
        )
        self.AXO_ENDPOINT_LOG_OUTPUT_PATH: Optional[str] = os.environ.get(
            "AXO_ENDPOINT_LOG_OUTPUT_PATH"
        )
        self.AXO_ENDPOINT_LOG_ERROR_OUTPUT_PATH: Optional[str] = os.environ.get(
            "AXO_ENDPOINT_LOG_ERROR_OUTPUT_PATH"
        )
        self.AXO_ENDPOINT_LOG_CONSOLE_LEVEL: int = _level(
            "AXO_ENDPOINT_LOG_CONSOLE_LEVEL", "DEBUG"
        )
        self.AXO_ENDPOINT_LOG_FILE_LEVEL: int = _level("AXO_ENDPOINT_LOG_FILE_LEVEL", "INFO")
        self.AXO_ENDPOINT_LOG_ERROR_FILE: bool = _bool("AXO_ENDPOINT_LOG_ERROR_FILE", "false")
        self.AXO_ENDPOINT_LOG_ROTATION_WHEN: str = os.environ.get(
            "AXO_ENDPOINT_LOG_ROTATION_WHEN", "midnight"
        )
        self.AXO_ENDPOINT_LOG_ROTATION_INTERVAL: int = _int(
            "AXO_ENDPOINT_LOG_ROTATION_INTERVAL", 1
        )
        self.AXO_ENDPOINT_LOG_JSON_INDENT: Optional[int] = _indent("AXO_ENDPOINT_LOG_JSON_INDENT")
        self.AXO_ENDPOINT_LOG_USE_RICH: bool = _bool("AXO_ENDPOINT_LOG_USE_RICH", "false")
        self.AXO_ENDPOINT_LOG_COLORIZE: bool = _bool("AXO_ENDPOINT_LOG_COLORIZE", "true")

        # Container runtime
        self.AXO_ENDPOINT_CONTAINER_BACKEND: str = os.environ.get(
            "AXO_ENDPOINT_CONTAINER_BACKEND", "docker"
        )
        self.AXO_ENDPOINT_CONTAINER_NETWORK: str = os.environ.get(
            "AXO_ENDPOINT_CONTAINER_NETWORK", "axo-net"
        )
        self.AXO_ENDPOINT_CONTAINER_RESULT_BIND: str = os.environ.get(
            "AXO_ENDPOINT_CONTAINER_RESULT_BIND", "tcp://0.0.0.0:5557"
        )
        self.AXO_ENDPOINT_CONTAINER_JOB_PORT: int = _int("AXO_ENDPOINT_CONTAINER_JOB_PORT", 5600)
        self.AXO_ENDPOINT_CONTAINER_FASTAPI_PORT: int = _int(
            "AXO_ENDPOINT_CONTAINER_FASTAPI_PORT", 8000
        )
        self.AXO_ENDPOINT_CONTAINER_READINESS_TIMEOUT_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_CONTAINER_READINESS_TIMEOUT_SECONDS", "60.0")
        )
        self.AXO_ENDPOINT_CONTAINER_PIP_CACHE_VOLUME: str = os.environ.get(
            "AXO_ENDPOINT_CONTAINER_PIP_CACHE_VOLUME", "axo-pip-cache"
        )
        self.AXO_ENDPOINT_CONTAINER_RUNNER_IMAGE: str = os.environ.get(
            "AXO_ENDPOINT_CONTAINER_RUNNER_IMAGE", "axo-runner"
        )
        self.AXO_ENDPOINT_CONTAINER_AUTO_BUILD_IMAGE: bool = _bool(
            "AXO_ENDPOINT_CONTAINER_AUTO_BUILD_IMAGE", "true"
        )
        self.AXO_ENDPOINT_CONTAINER_MEMORY_LIMIT_BYTES: int = _int(
            "AXO_ENDPOINT_CONTAINER_MEMORY_LIMIT_BYTES", 1024 * 1024 * 1024
        )
        self.AXO_ENDPOINT_CONTAINER_CPU_LIMIT: float = float(
            os.environ.get("AXO_ENDPOINT_CONTAINER_CPU_LIMIT", "1.0")
        )

        # External API publishing -- unset by default, gates the entire
        # feature (no publisher/bridge constructed, no events built at all)
        self.AXO_ENDPOINT_API_URI: Optional[str] = os.environ.get("AXO_ENDPOINT_API_URI") or None
        self.AXO_ENDPOINT_API_PUBLISH_TIMEOUT_MS: int = _int(
            "AXO_ENDPOINT_API_PUBLISH_TIMEOUT_MS", 1000
        )

        # Optional VirtualEnvironment this endpoint starts assigned to. Unset
        # means "unassigned" -- reassignment afterward happens at runtime via
        # the VIRTUAL_ENV_ASSIGN command, not by restarting with a new value.
        self.AXO_ENDPOINT_VIRTUAL_ENV_ID: Optional[str] = (
            os.environ.get("AXO_ENDPOINT_VIRTUAL_ENV_ID") or None
        )

        # Cluster-wide container concurrency: how the leader picks among a
        # function's existing owners when placing a job that can't be
        # satisfied by growing a new container here.
        self.AXO_ENDPOINT_LOAD_BALANCE_STRATEGY: str = os.environ.get(
            "AXO_ENDPOINT_LOAD_BALANCE_STRATEGY", "round_robin"
        )

        # Job result replication (executor -> leader -> every endpoint)
        self.AXO_ENDPOINT_RESULT_REPLICATION_MAX_RETRIES: int = _int(
            "AXO_ENDPOINT_RESULT_REPLICATION_MAX_RETRIES", 5
        )
        self.AXO_ENDPOINT_RESULT_REPLICATION_RETRY_BACKOFF_BASE_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_RESULT_REPLICATION_RETRY_BACKOFF_BASE_SECONDS", "1.0")
        )

        # Leader-owned, paginated background re-verification of every job
        # result's consistency across the cluster.
        self.AXO_ENDPOINT_RESULT_CONSISTENCY_CHECK_INTERVAL_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_RESULT_CONSISTENCY_CHECK_INTERVAL_SECONDS", "1800.0")
        )
        self.AXO_ENDPOINT_RESULT_CONSISTENCY_CHECK_CHUNK_SIZE: int = _int(
            "AXO_ENDPOINT_RESULT_CONSISTENCY_CHECK_CHUNK_SIZE", 50
        )

    def update(self, **kwargs) -> None:
        """Overrides one or more settings after creation. Unknown setting names are ignored."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
