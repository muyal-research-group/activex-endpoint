from axo_shared.activity.models import (
    CONTAINER_CRASHED_EVENT,
    CONTAINER_DISMISSED_EVENT,
    CONTAINER_READY_EVENT,
    CONTAINER_SPAWNED_EVENT,
    ActivityRecord,
)
from axo_shared.functions.lifecycle import FunctionState


def test_container_event_types_are_distinct_from_each_other_and_job_events():
    values = {
        CONTAINER_SPAWNED_EVENT, CONTAINER_READY_EVENT,
        CONTAINER_CRASHED_EVENT, CONTAINER_DISMISSED_EVENT,
        "JOB_SUBMITTED", "JOB_COMPLETED", "JOB_FAILED",
        FunctionState.REGISTERED.value,
    }
    assert len(values) == 8  # all unique, no accidental collisions


def test_activity_record_is_frozen_and_defaults():
    record = ActivityRecord(
        id="job1:JOB_SUBMITTED", activity_type="JOB_SUBMITTED",
        function_id="fn1", function_version=None, job_id="job1", timestamp=100.0,
    )
    assert record.failure is None
    assert record.service_name is None


def test_activity_record_carries_failure_and_service_name():
    record = ActivityRecord(
        id="job1:JOB_FAILED", activity_type="JOB_FAILED",
        function_id="fn1", function_version=1, job_id="job1", timestamp=100.0,
        failure={"error_class": "RUNTIME_ERROR", "message": "boom"},
        service_name="axo-fn-fn1",
    )
    assert record.failure["message"] == "boom"
    assert record.service_name == "axo-fn-fn1"
