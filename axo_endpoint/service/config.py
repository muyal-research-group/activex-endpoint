from __future__ import annotations

import os
from typing import List


class Config:
    """Holds all the settings for this endpoint, read from AXO_ENDPOINT_* environment variables."""

    def __init__(self) -> None:
        # Identity
        self.AXO_ENDPOINT_ID: str = os.environ.get("AXO_ENDPOINT_ID", "axo-endpoint-0")

        # Transport
        self.AXO_ENDPOINT_ROUTER_BIND: str = os.environ.get(
            "AXO_ENDPOINT_ROUTER_BIND", "tcp://0.0.0.0:5555"
        )
        self.AXO_ENDPOINT_PUB_BIND: str = os.environ.get("AXO_ENDPOINT_PUB_BIND", "tcp://0.0.0.0:5556")
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
        self.AXO_ENDPOINT_QUEUE_MAX_DEPTH: int = int(os.environ.get("AXO_ENDPOINT_QUEUE_MAX_DEPTH", "1000"))
        self.AXO_ENDPOINT_QUEUE_WORKERS: int = int(os.environ.get("AXO_ENDPOINT_QUEUE_WORKERS", "4"))

        # Process runtime: idle/recycle
        self.AXO_ENDPOINT_WORKER_IDLE_TTL_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_WORKER_IDLE_TTL_SECONDS", "300.0")
        )
        self.AXO_ENDPOINT_WORKER_GC_INTERVAL_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_WORKER_GC_INTERVAL_SECONDS", "30.0")
        )
        self.AXO_ENDPOINT_WORKER_MAX_INVOCATIONS: int = int(
            os.environ.get("AXO_ENDPOINT_WORKER_MAX_INVOCATIONS", "0")
        )  # 0 = unlimited

        # Process runtime: rlimits
        self.AXO_ENDPOINT_WORKER_RLIMIT_AS_BYTES: int = int(
            os.environ.get("AXO_ENDPOINT_WORKER_RLIMIT_AS_BYTES", str(512 * 1024 * 1024))
        )
        self.AXO_ENDPOINT_WORKER_RLIMIT_CPU_SECONDS: int = int(
            os.environ.get("AXO_ENDPOINT_WORKER_RLIMIT_CPU_SECONDS", "30")
        )

        # Scratch directories
        self.AXO_ENDPOINT_SCRATCH_ROOT: str = os.environ.get(
            "AXO_ENDPOINT_SCRATCH_ROOT", "/tmp/axo_endpoint/scratch"
        )
        self.AXO_ENDPOINT_SCRATCH_GC_INTERVAL_SECONDS: float = float(
            os.environ.get("AXO_ENDPOINT_SCRATCH_GC_INTERVAL_SECONDS", "60.0")
        )

    def update(self, **kwargs) -> None:
        """Overrides one or more settings after creation. Unknown setting names are ignored."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
