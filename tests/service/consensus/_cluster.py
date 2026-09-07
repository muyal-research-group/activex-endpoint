"""Test-only helper for spinning up a small real mesh of App instances.

Note: unlike the single-node heartbeat tests (which use ipc:// sockets),
these use real tcp://127.0.0.1 addresses on freshly allocated ports. That's
required here (not just convenient) because ``resolve_peer_address`` always
rebuilds addresses as ``tcp://<host>:<port>`` regardless of the original
bind scheme -- an ipc:// bind address can't round-trip through it. With
AXO_ENDPOINT_LOCAL_MODE=true, peer addresses resolve to tcp://localhost:<port>.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from typing import Callable, List, Optional

from axo_endpoint.config import Config
from axo_endpoint.service.app import App


def free_tcp_port() -> int:
    """Asks the OS for a free tcp port on localhost."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def spin_up_node(
    tmp_path,
    monkeypatch,
    node_id: str,
    sub_connect: Optional[List[str]] = None,
    **env_overrides: str,
) -> App:
    """Builds and starts a real App on tcp://127.0.0.1, in a daemon thread.

    Uses a short heartbeat interval/TTL and a short replication idle window so
    tests don't need long sleeps. Returns the started App.
    """
    env = {
        "AXO_ENDPOINT_ID": node_id,
        "AXO_ENDPOINT_ROUTER_BIND": f"tcp://127.0.0.1:{free_tcp_port()}",
        "AXO_ENDPOINT_PUB_BIND": f"tcp://127.0.0.1:{free_tcp_port()}",
        "AXO_ENDPOINT_CONTAINER_RESULT_BIND": f"tcp://127.0.0.1:{free_tcp_port()}",
        "AXO_ENDPOINT_SCRATCH_ROOT": str(tmp_path / f"{node_id}-scratch"),
        "AXO_ENDPOINT_DATAIO_FS_ROOT": str(tmp_path / f"{node_id}-dataio"),
        "AXO_ENDPOINT_SUB_CONNECT": ",".join(sub_connect or []),
        "AXO_ENDPOINT_LOCAL_MODE": "true",
        "AXO_ENDPOINT_LOG_DISABLED": "true",
        "AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS": "0.1",
        "AXO_ENDPOINT_HEARTBEAT_TTL_SECONDS": "1.0",
        "AXO_ENDPOINT_CONSENSUS_REPLICATION_IDLE_SECONDS": "0.2",
        "AXO_ENDPOINT_CONSENSUS_REPLICATION_MAX_DIRTY": "50",
        "AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS": "2.0",
        "AXO_ENDPOINT_BLOB_REPLICATION_IDLE_SECONDS": "0.2",
    }
    env.update(env_overrides)
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))

    app = App(Config())
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    return app


def wait_until(predicate: Callable[[], bool], timeout: float = 5.0, interval: float = 0.05) -> bool:
    """Polls ``predicate`` until it's true or ``timeout`` seconds elapse."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
