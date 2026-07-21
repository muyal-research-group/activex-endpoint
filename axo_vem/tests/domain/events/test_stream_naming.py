import pytest

from axo_shared.events import models

from axo_vem.domain.events.stream_naming import stream_name_for


def test_endpoint_events_route_to_endpoints_stream():
    assert stream_name_for(models.ENDPOINT_STARTED, "n0", {}) == "endpoints-n0"
    assert stream_name_for(models.ENDPOINT_METRICS_REPORTED, "n0", {}) == "endpoints-n0"
    assert stream_name_for(models.ENDPOINT_STOPPED, "n0", {}) == "endpoints-n0"


def test_endpoint_virtual_env_events_route_to_endpoints_stream():
    assert stream_name_for(models.ENDPOINT_VIRTUAL_ENV_ASSIGNED, "n0", {}) == "endpoints-n0"
    assert stream_name_for(models.ENDPOINT_VIRTUAL_ENV_DETACHED, "n0", {}) == "endpoints-n0"


def test_function_events_route_to_functions_stream_by_function_id_and_version():
    data = {"function_id": "add", "version": 1}
    assert stream_name_for(models.FUNCTION_REGISTERED, "n0", data) == "functions-add-1"
    assert stream_name_for(models.FUNCTION_DEPLOYED, "n0", data) == "functions-add-1"
    assert stream_name_for(models.FUNCTION_ACTIVATED, "n0", data) == "functions-add-1"
    assert stream_name_for(models.FUNCTION_DEACTIVATED, "n0", data) == "functions-add-1"
    assert stream_name_for(models.FUNCTION_UPDATED, "n0", data) == "functions-add-1"
    assert stream_name_for(models.FUNCTION_STOPPED, "n0", data) == "functions-add-1"
    assert stream_name_for(models.FUNCTION_CRASHED, "n0", data) == "functions-add-1"
    assert stream_name_for(models.FUNCTION_DELETED, "n0", data) == "functions-add-1"

    other_version = {"function_id": "add", "version": 2}
    assert stream_name_for(models.FUNCTION_REGISTERED, "n0", other_version) == "functions-add-2"


def test_function_build_events_route_by_function_id_or_base_image():
    data_with_function = {"function_id": "add", "python_version": "3.11"}
    assert stream_name_for(models.FUNCTION_BUILD_STARTED, "n0", data_with_function) == "functions-add"

    data_without_function = {"function_id": None, "python_version": "3.11"}
    assert stream_name_for(
        models.FUNCTION_BUILD_STARTED, "n0", data_without_function,
    ) == "functions-base-image-py3.11"


def test_consensus_events_route_to_consensus_stream_by_endpoint_id():
    data = {"leader_ids": ["n0"], "term": 1}
    assert stream_name_for(models.LEADER_ELECTED, "n0", data) == "consensus-n0"
    assert stream_name_for(models.CONSENSUS_VIEW_CHANGED, "n1", data) == "consensus-n1"
    assert stream_name_for(models.CLUSTER_QUORUM_LOST, "n0", data) == "consensus-n0"
    assert stream_name_for(models.CLUSTER_DEGRADED, "n0", data) == "consensus-n0"


def test_job_events_route_to_activity_stream_by_function_id():
    data = {"function_id": "add", "job_id": "job1"}
    assert stream_name_for(models.JOB_QUEUED, "n0", data) == "activity-add"
    assert stream_name_for(models.JOB_STARTED, "n0", data) == "activity-add"
    assert stream_name_for(models.JOB_COMPLETED, "n0", data) == "activity-add"
    assert stream_name_for(models.JOB_FAILED, "n0", data) == "activity-add"


def test_data_bucket_created_routes_to_buckets_stream_by_name():
    assert stream_name_for(models.DATA_BUCKET_CREATED, "n0", {"name": "b1", "quota_bytes": 100}) == "buckets-b1"


def test_data_registered_and_upload_completed_route_to_buckets_stream_by_bucket_prefix():
    bucketed = {"name": "b1/key1", "version": 1}
    assert stream_name_for(models.DATA_REGISTERED, "n0", bucketed) == "buckets-b1"
    assert stream_name_for(models.DATA_UPLOAD_COMPLETED, "n0", bucketed) == "buckets-b1"
    assert stream_name_for(models.DATA_DELETED, "n0", bucketed) == "buckets-b1"

    unbucketed = {"name": "df1", "version": 1}
    assert stream_name_for(models.DATA_REGISTERED, "n0", unbucketed) == "buckets-df1"
    assert stream_name_for(models.DATA_UPLOAD_COMPLETED, "n0", unbucketed) == "buckets-df1"
    assert stream_name_for(models.DATA_DELETED, "n0", unbucketed) == "buckets-df1"


def test_unknown_event_type_raises():
    with pytest.raises(ValueError):
        stream_name_for("NotARealEventType", "n0", {})
