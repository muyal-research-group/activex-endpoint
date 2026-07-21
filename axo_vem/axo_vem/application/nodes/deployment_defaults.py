from __future__ import annotations

from typing import Dict

# Every AXO_ENDPOINT_* variable a node reads, with the same default values
# axo_endpoint's own Config falls back to (mirrors .env.prod, the
# authoritative baseline profile for a real deployment). Exposed via
# GET /endpoints/deployment-defaults so a caller (e.g. the axo-ui deploy
# form) can show every configurable variable pre-filled, then override any
# subset via LaunchEndpointNodeUseCase's env_overrides.
#
# AXO_ENDPOINT_ID, AXO_ENDPOINT_SUB_CONNECT, AXO_ENDPOINT_API_URI,
# AXO_ENDPOINT_ROUTER_BIND, and AXO_ENDPOINT_VIRTUAL_ENV_ID are listed here
# for completeness/display, but LaunchEndpointNodeUseCase always sets them
# itself from its own explicit parameters -- values supplied for these keys
# via env_overrides are ignored, not merged, since a stale/mistaken override
# here would silently break mesh membership.
DEPLOYMENT_DEFAULTS: Dict[str, str] = {
    "AXO_ENDPOINT_ID": "axo-endpoint-0",
    "AXO_ENDPOINT_LOCAL_MODE": "false",
    "AXO_ENDPOINT_ROUTER_BIND": "tcp://0.0.0.0:5555",
    "AXO_ENDPOINT_PUB_BIND": "tcp://0.0.0.0:5556",
    "AXO_ENDPOINT_SUB_CONNECT": "",
    "AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS": "5.0",
    "AXO_ENDPOINT_HEARTBEAT_TTL_SECONDS": "30.0",
    "AXO_ENDPOINT_CONSENSUS_REPLICATION_IDLE_SECONDS": "2.0",
    "AXO_ENDPOINT_CONSENSUS_REPLICATION_MAX_DIRTY": "50",
    "AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS": "3.0",
    "AXO_ENDPOINT_CONSENSUS_BLOB_CHUNK_BYTES": "262144",
    "AXO_ENDPOINT_CONSENSUS_BLOB_RATE_LIMIT_BYTES_PER_SECOND": "1048576",
    "AXO_ENDPOINT_CONSENSUS_BLOB_TICK_INTERVAL_SECONDS": "0.1",
    "AXO_ENDPOINT_BLOB_REPLICATION_IDLE_SECONDS": "60.0",
    "AXO_ENDPOINT_BLOB_REPLICATION_ENABLED_KINDS": "fs",
    "AXO_ENDPOINT_BLOB_REPLICATION_RECHECK_SECONDS": "300.0",
    "AXO_ENDPOINT_ACTIVITY_LOG_MAX_ENTRIES": "10000",
    "AXO_ENDPOINT_QUEUE_MAX_DEPTH": "1000",
    "AXO_ENDPOINT_QUEUE_WORKERS": "8",
    "AXO_ENDPOINT_WORKER_IDLE_TTL_SECONDS": "60.0",
    "AXO_ENDPOINT_WORKER_GC_INTERVAL_SECONDS": "30.0",
    "AXO_ENDPOINT_WORKER_MAX_INVOCATIONS": "0",
    "AXO_ENDPOINT_WORKER_RLIMIT_AS_BYTES": "536870912",
    "AXO_ENDPOINT_WORKER_RLIMIT_CPU_SECONDS": "30",
    "AXO_ENDPOINT_SCRATCH_ROOT": "/tmp/axo_endpoint/scratch",
    "AXO_ENDPOINT_SCRATCH_GC_INTERVAL_SECONDS": "60.0",
    "AXO_ENDPOINT_DATAIO_FS_ROOT": "/tmp/axo_endpoint/dataio",
    "AXO_ENDPOINT_DATAIO_TIMEOUT_SECONDS": "30.0",
    "AXO_ENDPOINT_LOG_LEVEL": "DEBUG",
    "AXO_ENDPOINT_LOG_DISABLED": "false",
    "AXO_ENDPOINT_LOG_TO_FILE": "true",
    "AXO_ENDPOINT_LOG_PATH": ".axo_endpoint/log",
    "AXO_ENDPOINT_LOG_FILENAME": "axo_endpoint",
    "AXO_ENDPOINT_LOG_OUTPUT_PATH": "",
    "AXO_ENDPOINT_LOG_ERROR_OUTPUT_PATH": "",
    "AXO_ENDPOINT_LOG_CONSOLE_LEVEL": "DEBUG",
    "AXO_ENDPOINT_LOG_FILE_LEVEL": "INFO",
    "AXO_ENDPOINT_LOG_ERROR_FILE": "true",
    "AXO_ENDPOINT_LOG_ROTATION_WHEN": "midnight",
    "AXO_ENDPOINT_LOG_ROTATION_INTERVAL": "1",
    "AXO_ENDPOINT_LOG_JSON_INDENT": "2",
    "AXO_ENDPOINT_LOG_USE_RICH": "true",
    "AXO_ENDPOINT_LOG_COLORIZE": "true",
    "AXO_ENDPOINT_CONTAINER_NETWORK": "axo-net",
    "AXO_ENDPOINT_API_URI": "",
    "AXO_ENDPOINT_API_PUBLISH_TIMEOUT_MS": "1000",
    "AXO_ENDPOINT_VIRTUAL_ENV_ID": "",
}

# Keys LaunchEndpointNodeUseCase always sets itself -- values for these in
# env_overrides are ignored (see module docstring above).
MESH_IDENTITY_KEYS = frozenset({
    "AXO_ENDPOINT_ID", "AXO_ENDPOINT_SUB_CONNECT", "AXO_ENDPOINT_API_URI",
    "AXO_ENDPOINT_ROUTER_BIND", "AXO_ENDPOINT_VIRTUAL_ENV_ID",
})
