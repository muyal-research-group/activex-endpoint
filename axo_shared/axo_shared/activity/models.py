from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

# Container lifecycle event types, published on the EventBus -- distinct
# from log/catalog.py's Event.Container.* names (a separate namespace used
# only for structured logging). Before this, container spawn/ready/crashed/
# dismissed transitions were never published on the bus at all, only logged.
CONTAINER_SPAWNED_EVENT = "CONTAINER_SPAWNED"
CONTAINER_READY_EVENT = "CONTAINER_READY"
CONTAINER_CRASHED_EVENT = "CONTAINER_CRASHED"
CONTAINER_DISMISSED_EVENT = "CONTAINER_DISMISSED"

# Function/job lifecycle event types, published on the EventBus -- same
# "internal bus event type constant, not the axo_shared.events wire taxonomy
# value" role as the CONTAINER_* constants above, just for events introduced
# by the telemetry migration (see axo_endpoint.core.external.bridge, which
# maps these onto the wire taxonomy's FunctionStopped/FunctionCrashed/
# FunctionBuild*/FunctionDeleted*/JobStarted events).
# FUNCTION_STOPPED_EVENT: graceful teardown only (idle-TTL/max-invocations
# sweep, explicit container dismissal). FUNCTION_CRASHED_EVENT: a process
# worker's ungraceful exit -- previously folded into the same event as
# FUNCTION_STOPPED_EVENT (distinguished only by a "crash" reason string),
# now a distinct event/constant.
FUNCTION_STOPPED_EVENT = "FUNCTION_STOPPED"
FUNCTION_CRASHED_EVENT = "FUNCTION_CRASHED"
FUNCTION_UPDATED_EVENT = "FUNCTION_UPDATED"
FUNCTION_BUILD_STARTED_EVENT = "FUNCTION_BUILD_STARTED"
FUNCTION_BUILD_COMPLETED_EVENT = "FUNCTION_BUILD_COMPLETED"
FUNCTION_BUILD_FAILED_EVENT = "FUNCTION_BUILD_FAILED"
FUNCTION_DELETED_EVENT = "FUNCTION_DELETED"
FUNCTION_DELETE_FAILED_EVENT = "FUNCTION_DELETE_FAILED"
FUNCTION_REGISTER_FAILED_EVENT = "FUNCTION_REGISTER_FAILED"
# Process-runtime worker spawn success/failure -- the container-runtime
# equivalents are CONTAINER_SPAWNED_EVENT/CONTAINER_READY_EVENT (success) and
# CONTAINER_CRASHED_EVENT (failure) above; ExternalEventForwardingBridge
# folds all of these onto the same FunctionDeployed/FunctionDeployFailed
# wire taxonomy events, distinguished only by runtime_type.
FUNCTION_DEPLOYED_EVENT = "FUNCTION_DEPLOYED"
FUNCTION_DEPLOY_FAILED_EVENT = "FUNCTION_DEPLOY_FAILED"
JOB_STARTED_EVENT = "JOB_STARTED"
# A follower node absorbed a replicated FunctionRecord via
# RegistrySyncBridge.apply_incoming (STATE_SYNC_PUSH or a STATE_SYNC_PULL
# catch-up) -- distinct from FunctionState.REGISTERED.value, which only
# fires on the node that actually processed the live FUNCTION_REGISTER
# command. ExternalEventForwardingBridge.on_function_event is reused
# unchanged for this: from axo_vem's perspective "this node has the
# record" is the same fact whichever event announced it.
FUNCTION_REPLICATED_EVENT = "FUNCTION_REPLICATED"


@dataclass(frozen=True)
class ActivityRecord:
    """One entry in the append-only activity feed -- one per raw lifecycle
    event (job or container), not an upserted per-job status row. Matches an
    activity *feed* and needs zero cross-event correlation logic in whatever
    produces these; a UI wanting a job's full timeline joins/filters by
    job_id/function_id itself.

    This stays a plain dataclass (not Pydantic) -- unlike axo_shared.events,
    it never crosses the ZMQ envelope/wire boundary; it's purely local,
    in-process Repository[T] storage for this node's own ACTIVITY_LIST feed.
    """

    id: str
    activity_type: str
    function_id: str
    function_version: Optional[int]
    job_id: Optional[str]
    timestamp: float
    failure: Optional[Dict[str, Any]] = None
    service_name: Optional[str] = None
