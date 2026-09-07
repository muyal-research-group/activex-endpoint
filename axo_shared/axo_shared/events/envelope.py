from __future__ import annotations

from typing import Any, Dict, Tuple, Type

from option import Err, Ok, Result

from axo_shared import wire
from axo_shared.errors import AxoError, MalformedEventEnvelopeError
from axo_shared.events import models
from axo_shared.protocol import Command

SCHEMA_VERSION = 1

# Maps each event_type constant to the Pydantic model it rehydrates into --
# used by the projector (axo_vem) to reconstruct a typed event from
# decoded wire data. Endpoint-side publishing never needs this, only the
# consuming side. Models that are defined for taxonomy completeness only
# (never actually published -- see events/models.py's module notes) are
# still listed here so a manually-constructed event of that type would still
# rehydrate correctly.
EVENT_TYPES: Dict[str, Type[Any]] = {
    models.ENDPOINT_DEPLOYED: models.EndpointDeployed,
    models.ENDPOINT_DEPLOY_FAILED: models.EndpointDeployFailed,
    models.ENDPOINT_STARTED: models.EndpointStarted,
    models.ENDPOINT_METRICS_REPORTED: models.EndpointMetricsReported,
    models.ENDPOINT_STOPPED: models.EndpointStopped,
    models.CLUSTER_ELECTION_INITIATED: models.ClusterElectionInitiated,
    models.CLUSTER_ELECTION_FAILED: models.ClusterElectionFailed,
    models.LEADER_ELECTED: models.LeaderElected,
    models.CONSENSUS_VIEW_CHANGED: models.ConsensusViewChanged,
    models.CLUSTER_QUORUM_LOST: models.ClusterQuorumLost,
    models.CLUSTER_QUORUM_RESTORED: models.ClusterQuorumRestored,
    models.CLUSTER_DEGRADED: models.ClusterDegraded,
    models.FUNCTION_REGISTERED: models.FunctionRegistered,
    models.FUNCTION_REGISTER_FAILED: models.FunctionRegisterFailed,
    models.FUNCTION_BUILD_STARTED: models.FunctionBuildStarted,
    models.FUNCTION_BUILD_COMPLETED: models.FunctionBuildCompleted,
    models.FUNCTION_BUILD_FAILED: models.FunctionBuildFailed,
    models.FUNCTION_DEPLOYED: models.FunctionDeployed,
    models.FUNCTION_DEPLOY_FAILED: models.FunctionDeployFailed,
    models.FUNCTION_ACTIVATED: models.FunctionActivated,
    models.FUNCTION_DEACTIVATED: models.FunctionDeactivated,
    models.FUNCTION_UPDATED: models.FunctionUpdated,
    models.FUNCTION_STOPPED: models.FunctionStopped,
    models.FUNCTION_CRASHED: models.FunctionCrashed,
    models.FUNCTION_DELETED: models.FunctionDeleted,
    models.FUNCTION_DELETE_FAILED: models.FunctionDeleteFailed,
    models.JOB_QUEUED: models.JobQueued,
    models.JOB_STARTED: models.JobStarted,
    models.JOB_COMPLETED: models.JobCompleted,
    models.JOB_FAILED: models.JobFailed,
    models.USER_PROFILE_CREATED: models.UserProfileCreated,
    models.USER_PROFILE_UPDATED: models.UserProfileUpdated,
    models.USER_PROFILE_DELETED: models.UserProfileDeleted,
    models.USER_PROFILE_USERNAME_UPDATED: models.UserProfileUsernameUpdated,
    models.USER_PROFILE_EMAIL_UPDATED: models.UserProfileEmailUpdated,
    models.VIRTUAL_ENV_CREATED: models.VirtualEnvironmentCreated,
    models.VIRTUAL_ENV_UPDATED: models.VirtualEnvironmentUpdated,
    models.VIRTUAL_ENV_DELETED: models.VirtualEnvironmentDeleted,
    models.ENDPOINT_VIRTUAL_ENV_ASSIGNED: models.EndpointVirtualEnvironmentAssigned,
    models.ENDPOINT_VIRTUAL_ENV_DETACHED: models.EndpointVirtualEnvironmentDetached,
}


def encode_event(event_type: str, endpoint_id: str, data: Dict[str, Any]) -> Command:
    """Wraps one taxonomy event as a Command carried over the existing wire
    protocol. ``endpoint_id`` is the reporting endpoint's id -- this path is
    only ever used for events genuinely published by a running axo_endpoint
    node (see axo_endpoint.service.transport.event_publisher.ZmqEventPublisher);
    UserProfile/VirtualEnvironment events originate inside axo_vem
    itself and are appended directly, never through this envelope."""
    return Command(
        operation=wire.EVENT_PUBLISH,
        content_type="application/json",
        envelope={
            "schema_version": SCHEMA_VERSION,
            "event_type": event_type,
            "endpoint_id": endpoint_id,
            "data": data,
        },
        payload=b"",
    )


def decode_event(command: Command) -> Result[Tuple[str, str, Dict[str, Any]], AxoError]:
    """Unwraps a Command produced by encode_event back into (event_type, endpoint_id, data)."""
    envelope = command.envelope
    missing = [k for k in ("event_type", "endpoint_id", "data") if k not in envelope]
    if missing:
        return Err(MalformedEventEnvelopeError(
            f"event envelope missing required keys: {missing}",
            context={"missing_keys": missing},
        ))
    return Ok((envelope["event_type"], envelope["endpoint_id"], envelope["data"]))


def rehydrate(event_type: str, data: Dict[str, Any]) -> Any:
    """Reconstructs the typed event dataclass instance from decoded wire data.
    Raises KeyError for an unknown event_type -- callers control what they append
    to Kurrent, so an unrecognized type here means a schema/version mismatch."""
    cls = EVENT_TYPES[event_type]
    return cls(**data)
