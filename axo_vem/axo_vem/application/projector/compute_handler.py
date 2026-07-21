from __future__ import annotations

from typing import Any, Dict, Optional

from axo_vem.domain.compute.consensus_recorder import ConsensusRecorder
from axo_vem.domain.compute.repository import EndpointRepository, FunctionRepository
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository
from axo_vem.domain.workspace.virtual_environment import stream_name as virtual_environment_stream_name
from axo_vem.infrastructure.transport.ws.broadcaster import Broadcaster

# Only these two consensus event types carry leader_ids -- the quorum events
# (ClusterQuorumLost/Restored/Degraded) report member counts, not an elected
# leader, so they never touch VE leader tracking below.
_LEADER_BEARING_EVENT_TYPES = frozenset({models.LEADER_ELECTED, models.CONSENSUS_VIEW_CHANGED})

ENDPOINT_EVENT_TYPES = frozenset({
    models.ENDPOINT_STARTED, models.ENDPOINT_METRICS_REPORTED, models.ENDPOINT_STOPPED,
    models.ENDPOINT_UNREACHABLE, models.ENDPOINT_RECOVERED,
    models.ENDPOINT_VIRTUAL_ENV_ASSIGNED, models.ENDPOINT_VIRTUAL_ENV_DETACHED,
})

_WS_TOPIC = "endpoints"
_WS_FUNCTIONS_TOPIC = "functions"

# Function-lifecycle events that carry the full function_id/version/
# runtime_type shape and belong in the functions collection --
# FunctionDeleted/FunctionDeleteFailed get a different treatment (soft-delete
# vs. plain $set) than the rest, handled separately below.
FUNCTION_EVENT_TYPES = frozenset({
    models.FUNCTION_REGISTERED, models.FUNCTION_REGISTER_FAILED,
    models.FUNCTION_DEPLOYED, models.FUNCTION_DEPLOY_FAILED,
    models.FUNCTION_ACTIVATED, models.FUNCTION_DEACTIVATED,
    models.FUNCTION_UPDATED,
    models.FUNCTION_STOPPED, models.FUNCTION_CRASHED,
})

CONSENSUS_EVENT_TYPES = frozenset({
    models.LEADER_ELECTED, models.CONSENSUS_VIEW_CHANGED,
    models.CLUSTER_QUORUM_LOST, models.CLUSTER_QUORUM_RESTORED, models.CLUSTER_DEGRADED,
})

# Neither event carries a status field itself (EventEnvelope's shared shape
# has none) -- derived here from which event fired, rather than changing the
# wire taxonomy, since event_type already unambiguously implies it.
_ENDPOINT_STATUS_BY_EVENT_TYPE = {
    models.ENDPOINT_STARTED: "running",
    models.ENDPOINT_STOPPED: "stopped",
    models.ENDPOINT_UNREACHABLE: "unreachable",
    models.ENDPOINT_RECOVERED: "running",
}

# Same "no event carries a status field, derive it from which one fired"
# rationale as _ENDPOINT_STATUS_BY_EVENT_TYPE above. FunctionRegistered/
# RegisterFailed/Updated aren't container-lifecycle events, so they're
# absent here and leave container_status untouched.
_FUNCTION_CONTAINER_STATUS_BY_EVENT_TYPE = {
    models.FUNCTION_DEPLOYED: "running",
    models.FUNCTION_ACTIVATED: "running",
    models.FUNCTION_DEPLOY_FAILED: "stopped",
    models.FUNCTION_DEACTIVATED: "stopped",
    models.FUNCTION_STOPPED: "stopped",
    models.FUNCTION_CRASHED: "stopped",
}


def apply(
    endpoint_repository: EndpointRepository,
    function_repository: FunctionRepository,
    consensus_recorder: ConsensusRecorder,
    event_type: str,
    data: Dict[str, Any],
    broadcaster: Optional[Broadcaster] = None,
    virtual_environment_repository: Optional[VirtualEnvironmentRepository] = None,
    event_publisher: Optional[EventPublisher] = None,
) -> None:
    """Endpoint/Function events are written via apply_event_data() (full
    event field set, preserving fidelity for the dict-based GET read model
    -- see domain/compute/repository.py's docstring), not the narrow
    save(aggregate) methods. Replaces projector/upserts.py's former
    upsert_endpoint/upsert_function/mark_function_deleted/upsert_consensus.

    Status-bearing endpoint events (STARTED/STOPPED/UNREACHABLE/RECOVERED --
    see _ENDPOINT_STATUS_BY_EVENT_TYPE) also broadcast over the shared WS
    broadcaster's "endpoints" topic, mirroring bucket_handler.py's
    DataRegistered broadcast: the same full payload just written via
    apply_event_data() (which has no return value), so a freshly-connected
    client -- or one that's never heard of this endpoint_id before -- has
    enough to render a brand new row, not just patch an already-rendered
    one. METRICS_REPORTED/VIRTUAL_ENV_ASSIGNED/DETACHED deliberately don't
    broadcast here: they carry no "status" field, and axo-ui's WS handler
    uses that field's presence to distinguish "this can seed a new row"
    from EndpointStatsPoller's separate, differently-shaped container_stats
    ticks on the same topic.

    Every FUNCTION_EVENT_TYPES member (registration through crash) and
    FUNCTION_DELETED also broadcast over the "functions" topic -- unlike
    endpoints, this topic carries no second, differently-shaped message
    type sharing it, so there's no "status field present" gate needed:
    every message here is always a full function payload, letting
    axo-ui's functions list page pick up a freshly registered function (or
    any later status change) without a manual reload. FUNCTION_ENDPOINT_
    DETACHED deliberately doesn't broadcast: it only prunes one entry from
    endpoint_id, an internal accounting detail no UI surfaces live today."""
    if event_type in ENDPOINT_EVENT_TYPES:
        status = _ENDPOINT_STATUS_BY_EVENT_TYPE.get(event_type)
        payload = {**data, "status": status} if status is not None else data
        endpoint_repository.apply_event_data(data["endpoint_id"], payload)
        if broadcaster is not None and status is not None:
            broadcaster.broadcast(_WS_TOPIC, payload)
    elif event_type in FUNCTION_EVENT_TYPES:
        container_status = _FUNCTION_CONTAINER_STATUS_BY_EVENT_TYPE.get(event_type)
        payload = {**data, "container_status": container_status} if container_status is not None else data
        function_repository.apply_event_data(payload)
        if broadcaster is not None:
            broadcaster.broadcast(_WS_FUNCTIONS_TOPIC, payload)
    elif event_type == models.FUNCTION_DELETED:
        function_repository.mark_deleted_from_event(data)
        if broadcaster is not None:
            broadcaster.broadcast(_WS_FUNCTIONS_TOPIC, {**data, "deleted_at": data["created_at"]})
    elif event_type == models.FUNCTION_ENDPOINT_DETACHED:
        function_repository.detach_endpoint_from_event(data)
    elif event_type in CONSENSUS_EVENT_TYPES:
        consensus_recorder.record(data["endpoint_id"], data)
        if event_type in _LEADER_BEARING_EVENT_TYPES and virtual_environment_repository is not None:
            _apply_leader_change(
                endpoint_repository, virtual_environment_repository, event_publisher, data,
            )


def _apply_leader_change(
    endpoint_repository: EndpointRepository,
    virtual_environment_repository: VirtualEnvironmentRepository,
    event_publisher: Optional[EventPublisher],
    data: Dict[str, Any],
) -> None:
    """LeaderElected/ConsensusViewChanged's own virtual_environment_id field
    is the *reporting* endpoint's VE, not the elected leader's -- any peer
    can publish "leader_ids=[X]", so the leader's VE must be looked up
    separately off its own endpoint doc (already populated independently by
    EndpointVirtualEnvironmentAssigned/Detached, so this is always
    resolvable by the time an election event arrives).

    This Bully implementation always elects exactly one leader (leader_ids
    is list-typed on the wire for forward compatibility only) -- guard the
    length rather than assume the type.

    There's only one mesh-wide leader at a time, so the previous holder's
    flag (on whatever VE it belonged to) is cleared unconditionally before
    the new one -- if any -- is set."""
    leader_ids = data.get("leader_ids") or []
    if len(leader_ids) != 1:
        return
    leader_endpoint_id = leader_ids[0]

    virtual_environment_repository.clear_leader_endpoint_id()

    leader_endpoint = endpoint_repository.get(leader_endpoint_id)
    ve_id = leader_endpoint.virtual_environment_id if leader_endpoint is not None else None
    if ve_id is None:
        return

    virtual_environment_repository.set_leader_endpoint_id(ve_id, leader_endpoint_id)

    if event_publisher is not None:
        event = models.VirtualEnvironmentLeaderChanged(
            virtual_environment_id=ve_id, leader_endpoint_id=leader_endpoint_id,
        )
        event_publisher.append_to_stream(
            virtual_environment_stream_name(ve_id), models.VIRTUAL_ENV_LEADER_CHANGED,
            event.model_dump(mode="json"),
        )
