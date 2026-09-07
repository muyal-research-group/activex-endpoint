from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from axo_shared.runtime.spec import ContainerMode


class ContainerStatus(str, Enum):
    STARTING      = "STARTING"
    BOOTSTRAPPING = "BOOTSTRAPPING"
    READY         = "READY"
    BUSY          = "BUSY"
    IDLE          = "IDLE"
    CRASHED       = "CRASHED"
    DISMISSED     = "DISMISSED"


@dataclass
class ContainerHandle:
    """Tracks one live container or Swarm service running a single function."""

    function_id: str
    version: int
    service_name: str
    mode: ContainerMode
    zmq_address: str
    http_address: str
    container_id: Optional[str] = None
    service_id: Optional[str] = None
    status: ContainerStatus = ContainerStatus.STARTING
    last_used: float = 0.0
    invocation_count: int = 0
    # This handle's position in its (function_id, version)'s pool -- 0 for
    # the first/only member. Used for naming and pool bookkeeping only.
    pool_index: int = 0
    # Stashed from RuntimeSpec.max_duration_seconds at summon time (a
    # per-(function, version) constant) -- the pump doesn't otherwise have
    # access to the RuntimeSpec. 0 = unlimited, same convention as the spec.
    max_duration_seconds: float = 0
    ready_event: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    # The job_id currently dispatched to this container, if any -- set right
    # before dispatch, cleared once its result arrives. Lets cancel(job_id)
    # find the right container to dismiss.
    current_job_id: Optional[str] = None


def sanitize_container_name(function_id: str, version: int, pool_index: int = 0) -> str:
    """Converts a function_id + version (+ pool member index, for
    RuntimeSpec.max_concurrency > 1) into a Docker/Swarm-safe DNS label.

    Rules: lowercase, replace _ with -, drop anything not [a-z0-9-], prefix fn-,
    append -v<version> and (only when pool_index > 0) -p<pool_index>,
    truncate total to 63 chars. pool_index 0 reproduces today's single-
    container name exactly, so max_concurrency=1 (the default) is unaffected.

    The slug -- not the assembled name -- is what gets truncated: function_ids
    are content hashes long enough (60+ chars) that truncating the full
    assembled string instead chops the -v/-p suffix off first, collapsing
    every version/pool member of a function onto one identical name (Docker
    409 "name already in use" on every spawn but the first).
    """
    slug = function_id.lower().replace("_", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = slug.strip("-") or "fn"
    suffix = f"-v{version}"
    if pool_index > 0:
        suffix = f"{suffix}-p{pool_index}"
    max_slug_len = 63 - len("fn-") - len(suffix)
    slug = slug[:max_slug_len]
    return f"fn-{slug}{suffix}"
