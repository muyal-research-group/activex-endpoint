from axo_shared import wire
from axo_shared.events import envelope, models


def test_encode_decode_round_trips_endpoint_started():
    event = models.EndpointStarted(
        endpoint_id="axo-endpoint-0",
        router_bind="tcp://0.0.0.0:5555",
        pub_bind="tcp://0.0.0.0:5556",
    )
    command = envelope.encode_event(models.ENDPOINT_STARTED, "axo-endpoint-0", event.model_dump(mode="json"))

    frames = wire.encode_command(command)
    decoded_command_result = wire.decode_command(frames)
    assert decoded_command_result.is_ok
    decoded_command = decoded_command_result.unwrap()

    result = envelope.decode_event(decoded_command)
    assert result.is_ok
    event_type, endpoint_id, data = result.unwrap()
    assert event_type == models.ENDPOINT_STARTED
    assert endpoint_id == "axo-endpoint-0"
    rehydrated = envelope.rehydrate(event_type, data)
    assert rehydrated.event_id == event.event_id
    assert rehydrated.created_at == event.created_at
    assert rehydrated.router_bind == event.router_bind


def test_encode_decode_round_trips_all_event_kinds():
    cases = [
        (models.ENDPOINT_METRICS_REPORTED, models.EndpointMetricsReported(
            endpoint_id="n0", metrics={"queue_depth": 3})),
        (models.ENDPOINT_STOPPED, models.EndpointStopped(endpoint_id="n0", uptime_ms=100.0)),
        (models.FUNCTION_REGISTERED, models.FunctionRegistered(
            endpoint_id="n0", function_id="add", version=1,
            runtime_spec={"type": "process"})),
        (models.FUNCTION_DEPLOYED, models.FunctionDeployed(endpoint_id="n0", function_id="add", version=1)),
        (models.FUNCTION_ACTIVATED, models.FunctionActivated(
            endpoint_id="n0", function_id="add", version=1, job_id="job1")),
        (models.FUNCTION_DEACTIVATED, models.FunctionDeactivated(
            endpoint_id="n0", function_id="add", version=1, state="COMPLETED")),
        (models.FUNCTION_UPDATED, models.FunctionUpdated(
            endpoint_id="n0", function_id="add", version=1, env_vars={"A": "1"})),
        (models.FUNCTION_STOPPED, models.FunctionStopped(
            endpoint_id="n0", function_id="add", version=1, reason="idle_ttl")),
        (models.FUNCTION_CRASHED, models.FunctionCrashed(endpoint_id="n0", function_id="add", version=1)),
        (models.FUNCTION_DELETED, models.FunctionDeleted(endpoint_id="n0", function_id="add", version=1)),
        (models.LEADER_ELECTED, models.LeaderElected(endpoint_id="n0", leader_ids=["n1"], term=2)),
        (models.CONSENSUS_VIEW_CHANGED, models.ConsensusViewChanged(
            endpoint_id="n0", term=2, was_leader=False, is_leader=True, leader_ids=["n0"])),
        (models.CLUSTER_QUORUM_LOST, models.ClusterQuorumLost(
            endpoint_id="n0", term=1, member_count=1, quorum_size=2)),
        (models.CLUSTER_DEGRADED, models.ClusterDegraded(
            endpoint_id="n0", term=1, member_count=2, quorum_size=2, evicted_peer_id="n1")),
        (models.JOB_QUEUED, models.JobQueued(endpoint_id="n0", job_id="job1", function_id="add")),
        (models.JOB_STARTED, models.JobStarted(endpoint_id="n0", job_id="job1", function_id="add")),
        (models.JOB_COMPLETED, models.JobCompleted(endpoint_id="n0", job_id="job1", function_id="add")),
        (models.ENDPOINT_VIRTUAL_ENV_ASSIGNED, models.EndpointVirtualEnvironmentAssigned(
            endpoint_id="n0", virtual_environment_id="ve1")),
        (models.ENDPOINT_VIRTUAL_ENV_DETACHED, models.EndpointVirtualEnvironmentDetached(
            endpoint_id="n0", previous_virtual_environment_id="ve1")),
    ]

    for event_type, event in cases:
        command = envelope.encode_event(event_type, "n0", event.model_dump(mode="json"))
        frames = wire.encode_command(command)
        decoded_command = wire.decode_command(frames).unwrap()
        result = envelope.decode_event(decoded_command)
        assert result.is_ok, f"{event_type} failed to decode"
        got_event_type, endpoint_id, data = result.unwrap()
        assert got_event_type == event_type
        rehydrated = envelope.rehydrate(got_event_type, data)
        assert rehydrated == event, f"{event_type} did not round-trip"


def test_job_failed_round_trips_with_nested_failure_detail():
    failure = models.FailureDetail(
        error_class="FUNCTION_RUNTIME_ERROR", error_code=0, component="runtime", message="boom",
    )
    event = models.JobFailed(endpoint_id="n0", job_id="job1", function_id="add", failure=failure)
    command = envelope.encode_event(models.JOB_FAILED, "n0", event.model_dump(mode="json"))
    frames = wire.encode_command(command)
    decoded_command = wire.decode_command(frames).unwrap()
    event_type, endpoint_id, data = envelope.decode_event(decoded_command).unwrap()
    rehydrated = envelope.rehydrate(event_type, data)
    assert rehydrated == event
    assert rehydrated.failure.message == "boom"


def test_decode_event_with_missing_keys_returns_err():
    from axo_shared.protocol import Command

    command = Command(
        operation=wire.EVENT_PUBLISH,
        content_type="application/json",
        envelope={"schema_version": 1, "event_type": models.ENDPOINT_STARTED},
        payload=b"",
    )
    result = envelope.decode_event(command)
    assert result.is_err


def test_event_publish_is_a_distinct_operation_constant():
    assert wire.EVENT_PUBLISH not in {
        wire.PING, wire.FUNCTION_REGISTER, wire.FUNCTION_DELETE, wire.JOB_SUBMIT, wire.JOB_RESULT, wire.METRICS,
    }
