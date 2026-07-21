from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from axo_shared.runtime.spec import ContainerMode


@dataclass(frozen=True)
class MountSpec:
    """One bind mount, backend-agnostic -- ContainerSpawner translates this
    into whichever shape each Docker SDK call needs (a "src:target:mode"
    string for a Swarm service, a {src: {"bind": target, "mode": mode}}
    dict for a plain container)."""

    source: str
    target: str
    mode: Literal["rw", "ro"] = "rw"


@dataclass
class SpawnedContainerHandle:
    """Identity/addressing only -- no invocation or readiness lifecycle
    (status, health checks, busy/idle tracking); that state stays with the
    caller, since it's specific to what the container is actually running
    (e.g. axo_endpoint's ContainerHandle tracks a function runner's own
    zmq_address/http_address/ready_event on top of this)."""

    name: str
    mode: ContainerMode
    container_id: Optional[str] = None
    service_id: Optional[str] = None


@dataclass(frozen=True)
class ContainerStats:
    """One point-in-time resource snapshot, the same numbers `docker stats`
    shows -- see ContainerSpawner.stats() for how each field is derived
    from the Docker SDK's raw stats JSON."""

    cpu_percent: float
    memory_usage: int
    memory_limit: int
    network_rx: int
    network_tx: int
