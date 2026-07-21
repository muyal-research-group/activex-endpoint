from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from axo_shared.events import models


def test_event_type_constants_are_distinct():
    constants = [
        models.ENDPOINT_DEPLOYED,
        models.ENDPOINT_DEPLOY_FAILED,
        models.ENDPOINT_STARTED,
        models.ENDPOINT_METRICS_REPORTED,
        models.ENDPOINT_STOPPED,
        models.CLUSTER_ELECTION_INITIATED,
        models.CLUSTER_ELECTION_FAILED,
        models.LEADER_ELECTED,
        models.CONSENSUS_VIEW_CHANGED,
        models.CLUSTER_QUORUM_LOST,
        models.CLUSTER_QUORUM_RESTORED,
        models.CLUSTER_DEGRADED,
        models.FUNCTION_REGISTERED,
        models.FUNCTION_REGISTER_FAILED,
        models.FUNCTION_BUILD_STARTED,
        models.FUNCTION_BUILD_COMPLETED,
        models.FUNCTION_BUILD_FAILED,
        models.FUNCTION_DEPLOYED,
        models.FUNCTION_DEPLOY_FAILED,
        models.FUNCTION_ACTIVATED,
        models.FUNCTION_DEACTIVATED,
        models.FUNCTION_UPDATED,
        models.FUNCTION_STOPPED,
        models.FUNCTION_CRASHED,
        models.FUNCTION_DELETED,
        models.FUNCTION_DELETE_FAILED,
        models.FUNCTION_ENDPOINT_DETACHED,
        models.JOB_QUEUED,
        models.JOB_STARTED,
        models.JOB_COMPLETED,
        models.JOB_FAILED,
        models.USER_PROFILE_CREATED,
        models.USER_PROFILE_UPDATED,
        models.USER_PROFILE_DELETED,
        models.USER_PROFILE_USERNAME_UPDATED,
        models.USER_PROFILE_EMAIL_UPDATED,
        models.VIRTUAL_ENV_CREATED,
        models.VIRTUAL_ENV_UPDATED,
        models.VIRTUAL_ENV_DELETED,
        models.ENDPOINT_VIRTUAL_ENV_ASSIGNED,
        models.ENDPOINT_VIRTUAL_ENV_DETACHED,
    ]
    assert len(constants) == len(set(constants))


def test_event_envelope_defaults_event_id_and_created_at():
    event = models.EndpointStarted(router_bind="tcp://0.0.0.0:5555", pub_bind="tcp://0.0.0.0:5556")
    assert UUID(event.event_id)  # raises ValueError if not a valid UUID
    assert event.created_at.tzinfo is not None
    assert event.created_at <= datetime.now(timezone.utc)
    assert event.user_id is None
    assert event.virtual_environment_id is None
    assert event.endpoint_id is None
    assert event.runtime_type is None


def test_event_envelope_is_frozen():
    event = models.EndpointStarted(router_bind="tcp://0.0.0.0:5555", pub_bind="tcp://0.0.0.0:5556")
    with pytest.raises(ValidationError):
        event.endpoint_id = "axo-endpoint-0"


def test_failure_detail_from_axo_error():
    from axo_shared.errors import MalformedEventEnvelopeError

    err = MalformedEventEnvelopeError("boom", context={"a": 1})
    failure = models.FailureDetail.from_axo_error(err, component="test_component")
    assert failure.error_class == "MALFORMED_EVENT_ENVELOPE"
    assert failure.error_code == 5004
    assert failure.component == "test_component"
    assert failure.message == "boom"
    assert failure.is_transient is False


def test_endpoint_started_fields():
    event = models.EndpointStarted(
        endpoint_id="axo-endpoint-0",
        router_bind="tcp://0.0.0.0:5555",
        pub_bind="tcp://0.0.0.0:5556",
    )
    assert event.endpoint_id == "axo-endpoint-0"


def test_endpoint_metrics_reported_defaults_to_empty_metrics():
    event = models.EndpointMetricsReported(endpoint_id="axo-endpoint-0")
    assert event.metrics == {}


def test_endpoint_stopped_fields():
    event = models.EndpointStopped(endpoint_id="axo-endpoint-0", uptime_ms=1234.5)
    assert event.uptime_ms == 1234.5


def test_function_registered_defaults_runtime_spec_and_owner_to_none():
    event = models.FunctionRegistered(endpoint_id="axo-endpoint-0", function_id="add", version=1)
    assert event.runtime_spec is None
    assert event.owner_user_id is None


def test_function_register_failed_requires_failure():
    failure = models.FailureDetail(
        error_class="REGISTRY_ERROR", error_code=1, component="registry", message="boom",
    )
    event = models.FunctionRegisterFailed(
        endpoint_id="axo-endpoint-0", function_id="add", version=1, failure=failure,
    )
    assert event.failure.message == "boom"


def test_function_deployed_activated_deactivated_fields():
    deployed = models.FunctionDeployed(endpoint_id="n0", function_id="add", version=1)
    activated = models.FunctionActivated(endpoint_id="n0", function_id="add", version=1, job_id="job1")
    deactivated = models.FunctionDeactivated(
        endpoint_id="n0", function_id="add", version=1, state="COMPLETED",
    )
    assert deployed.function_id == "add"
    assert activated.job_id == "job1"
    assert deactivated.state == "COMPLETED"


def test_function_stopped_reason_is_constrained():
    event = models.FunctionStopped(
        endpoint_id="n0", function_id="add", version=1, reason="idle_ttl",
    )
    assert event.reason == "idle_ttl"
    with pytest.raises(ValidationError):
        models.FunctionStopped(endpoint_id="n0", function_id="add", version=1, reason="not_a_reason")
    with pytest.raises(ValidationError):
        models.FunctionStopped(endpoint_id="n0", function_id="add", version=1, reason="crash")


def test_function_crashed_fields():
    event = models.FunctionCrashed(endpoint_id="n0", function_id="add", version=1, runtime_type="process")
    assert event.function_id == "add"
    assert event.version == 1
    assert event.runtime_type == "process"


def test_function_updated_fields():
    event = models.FunctionUpdated(
        endpoint_id="n0", function_id="add", version=1,
        params_schema=[{"name": "x", "type": "number"}], env_vars={"A": "1"},
    )
    assert event.params_schema == [{"name": "x", "type": "number"}]
    assert event.env_vars == {"A": "1"}


def test_function_build_events_allow_function_id_none():
    event = models.FunctionBuildStarted(python_version="3.11", image_tag="axo-runner:py3.11")
    assert event.function_id is None


def test_function_deleted_fields():
    event = models.FunctionDeleted(endpoint_id="n0", function_id="add", version=1)
    assert event.version == 1


def test_function_endpoint_detached_fields():
    event = models.FunctionEndpointDetached(endpoint_id="n0", function_id="add", version=1)
    assert event.endpoint_id == "n0"
    assert event.function_id == "add"
    assert event.version == 1


def test_leader_elected_fields():
    event = models.LeaderElected(endpoint_id="axo-endpoint-0", leader_ids=["axo-endpoint-1"], term=3)
    assert event.term == 3
    assert event.leader_ids == ["axo-endpoint-1"]


def test_consensus_view_changed_fields():
    event = models.ConsensusViewChanged(
        endpoint_id="axo-endpoint-0", term=3, was_leader=False, is_leader=True,
        leader_ids=["axo-endpoint-0"],
    )
    assert event.is_leader is True
    assert event.was_leader is False


def test_cluster_quorum_and_degraded_fields():
    lost = models.ClusterQuorumLost(endpoint_id="n0", term=1, member_count=1, quorum_size=2)
    restored = models.ClusterQuorumRestored(endpoint_id="n0", term=1, member_count=2, quorum_size=2)
    degraded = models.ClusterDegraded(
        endpoint_id="n0", term=1, member_count=2, quorum_size=2, evicted_peer_id="n1",
    )
    assert lost.member_count == 1
    assert restored.quorum_size == 2
    assert degraded.evicted_peer_id == "n1"


def test_job_pipeline_fields():
    queued = models.JobQueued(endpoint_id="n0", job_id="job1", function_id="add", version=1)
    started = models.JobStarted(endpoint_id="n0", job_id="job1", function_id="add")
    completed = models.JobCompleted(endpoint_id="n0", job_id="job1", function_id="add", duration_ms=12.0)
    failure = models.FailureDetail(
        error_class="FUNCTION_RUNTIME_ERROR", error_code=0, component="runtime", message="boom",
    )
    failed = models.JobFailed(endpoint_id="n0", job_id="job1", function_id="add", failure=failure)
    assert queued.version == 1
    assert started.job_id == "job1"
    assert completed.duration_ms == 12.0
    assert failed.failure.message == "boom"


def test_user_profile_created_uses_preferences_submodel():
    event = models.UserProfileCreated(
        user_id="u1", profile_photo="photo.png", preferences=models.Preferences(),
    )
    assert event.preferences.view_mode == "list"
    assert event.user_id == "u1"


def test_user_profile_username_email_updated_defined_but_standalone():
    username_event = models.UserProfileUsernameUpdated(user_id="u1", new_username="alice")
    email_event = models.UserProfileEmailUpdated(user_id="u1", new_email="alice@example.com")
    assert username_event.new_username == "alice"
    assert email_event.new_email == "alice@example.com"


def test_virtual_environment_created_fields():
    event = models.VirtualEnvironmentCreated(
        virtual_environment_id="ve1", name="prod", owner_user_id="u1",
        resource_quota=models.ResourceQuota(cpu=1.0, ram=512, disk=1024),
    )
    assert event.resource_quota.ram == 512


def test_virtual_environment_deleted_fields():
    event = models.VirtualEnvironmentDeleted(virtual_environment_id="ve1")
    assert event.virtual_environment_id == "ve1"


def test_endpoint_virtual_environment_assigned_uses_envelope_fields():
    event = models.EndpointVirtualEnvironmentAssigned(
        endpoint_id="axo-endpoint-0", virtual_environment_id="ve1",
    )
    assert event.virtual_environment_id == "ve1"


def test_endpoint_virtual_environment_detached_fields():
    event = models.EndpointVirtualEnvironmentDetached(
        endpoint_id="axo-endpoint-0", previous_virtual_environment_id="ve1",
    )
    assert event.previous_virtual_environment_id == "ve1"
