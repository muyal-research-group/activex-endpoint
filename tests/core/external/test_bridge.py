from axo_shared.activity.models import (
    CONTAINER_CRASHED_EVENT,
    CONTAINER_READY_EVENT,
    CONTAINER_SPAWNED_EVENT,
    FUNCTION_BUILD_COMPLETED_EVENT,
    FUNCTION_BUILD_FAILED_EVENT,
    FUNCTION_BUILD_STARTED_EVENT,
    FUNCTION_DELETED_EVENT,
    FUNCTION_DELETE_FAILED_EVENT,
    FUNCTION_DEPLOYED_EVENT,
    FUNCTION_DEPLOY_FAILED_EVENT,
    FUNCTION_CRASHED_EVENT,
    FUNCTION_STOPPED_EVENT,
    FUNCTION_REGISTER_FAILED_EVENT,
    JOB_STARTED_EVENT,
)
from axo_shared.events import models as event_models
from axo_shared.functions.lifecycle import FunctionState
from axo_shared.functions.params_schema import ParamSpec
from axo_shared.runtime.spec import RuntimeSpec

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.events.bus import Event
from axo_endpoint.core.external.bridge import ExternalEventForwardingBridge
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.results import FunctionResult
from axo_endpoint.core.storage import InMemoryStorageBackend
from axo_endpoint.core.storage.backend import StorageKey
from axo_endpoint.service.consensus_loop import (
    CLUSTER_DEGRADED_EVENT,
    CLUSTER_QUORUM_LOST_EVENT,
    CLUSTER_QUORUM_RESTORED_EVENT,
)


class _FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, event_type, data):
        self.published.append((event_type, data))


def _bridge(results=None, runtime_spec=None, params_schema=None):
    publisher = _FakePublisher()
    registry = FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=InMemoryEventBus())
    registry.register(
        function_id="add", name="add", code=b"", now=100.0,
        runtime_spec=runtime_spec, params_schema=params_schema,
    )
    bridge = ExternalEventForwardingBridge(
        publisher=publisher, endpoint_id="n0", results=results or InMemoryStorageBackend(),
        function_registry=registry,
    )
    return bridge, publisher, registry


def test_on_function_event_forwards_function_registered_with_runtime_type():
    bridge, publisher, _ = _bridge(runtime_spec=RuntimeSpec(type="process"))

    bridge.on_function_event(Event(
        event_type=FunctionState.REGISTERED.value,
        payload={"function_id": "add", "version": 1},
        timestamp=100.0,
    ))

    assert len(publisher.published) == 1
    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_REGISTERED
    assert data["function_id"] == "add"
    assert data["version"] == 1
    assert data["endpoint_id"] == "n0"
    assert data["name"] == "add"
    assert data["runtime_type"] == "process"
    assert data["runtime_spec"]["type"] == "process"


def test_on_function_event_forwards_params_schema():
    bridge, publisher, _ = _bridge(params_schema=[ParamSpec(name="x", type="number", required=True)])

    bridge.on_function_event(Event(
        event_type=FunctionState.REGISTERED.value,
        payload={"function_id": "add", "version": 1},
        timestamp=100.0,
    ))

    _event_type, data = publisher.published[0]
    assert data["params_schema"] == [{"name": "x", "type": "number", "required": True, "default": None}]


def test_events_are_stamped_with_the_current_virtual_environment_id():
    publisher = _FakePublisher()
    registry = FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=InMemoryEventBus())
    registry.register(function_id="add", name="add", code=b"", now=100.0)
    bridge = ExternalEventForwardingBridge(
        publisher=publisher, endpoint_id="n0", results=InMemoryStorageBackend(),
        function_registry=registry, get_virtual_environment_id=lambda: "ve1",
    )

    bridge.on_function_event(Event(
        event_type=FunctionState.REGISTERED.value, payload={"function_id": "add", "version": 1}, timestamp=100.0,
    ))

    _event_type, data = publisher.published[0]
    assert data["virtual_environment_id"] == "ve1"


def test_events_default_to_no_virtual_environment_id_when_not_wired():
    """No get_virtual_environment_id callback given -- e.g. a bridge built
    without the callback still works, just stamps None (matches every test
    above via the _bridge() helper, which doesn't pass one)."""
    bridge, publisher, _ = _bridge()

    bridge.on_function_event(Event(
        event_type=FunctionState.REGISTERED.value, payload={"function_id": "add", "version": 1}, timestamp=100.0,
    ))

    _event_type, data = publisher.published[0]
    assert data["virtual_environment_id"] is None


def test_on_function_register_failed_forwards_failure_detail():
    bridge, publisher, _ = _bridge()

    bridge.on_function_register_failed(Event(
        event_type=FUNCTION_REGISTER_FAILED_EVENT,
        payload={
            "function_id": "add", "version": 1,
            "failure": {
                "error_class": "STORAGE_ERROR", "error_code": 8000, "component": "function_registry",
                "message": "boom", "traceback": None, "is_transient": False,
            },
        },
        timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_REGISTER_FAILED
    assert data["failure"]["message"] == "boom"


def test_on_function_register_failed_skips_publish_when_version_unknown():
    """Regression test: registration itself failing means no version was
    ever assigned -- must never be faked as 0 (see
    test_on_function_deployed_skips_publish_when_version_unknown)."""
    bridge, publisher, _ = _bridge()

    bridge.on_function_register_failed(Event(
        event_type=FUNCTION_REGISTER_FAILED_EVENT,
        payload={
            "function_id": "add",
            "failure": {
                "error_class": "STORAGE_ERROR", "error_code": 8000, "component": "function_registry",
                "message": "boom", "traceback": None, "is_transient": False,
            },
        },
        timestamp=100.0,
    ))

    assert publisher.published == []


def test_on_function_deployed_from_process_event():
    bridge, publisher, _ = _bridge()

    bridge.on_function_deployed(Event(
        event_type=FUNCTION_DEPLOYED_EVENT, payload={"function_id": "add", "version": 1}, timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_DEPLOYED
    assert data["runtime_type"] == "process"


def test_on_function_deployed_from_container_events():
    bridge, publisher, _ = _bridge()

    for container_event_type in (CONTAINER_SPAWNED_EVENT, CONTAINER_READY_EVENT):
        publisher.published.clear()
        bridge.on_function_deployed(Event(
            event_type=container_event_type,
            payload={"function_id": "add", "version": 1, "service_name": "svc"},
            timestamp=100.0,
        ))
        event_type, data = publisher.published[0]
        assert event_type == event_models.FUNCTION_DEPLOYED
        assert data["runtime_type"] == "container"


def test_on_function_deployed_skips_publish_when_version_unknown():
    """Regression test: a missing version must never be faked as 0 -- that
    used to create a phantom "version 0" function record downstream with no
    runtime_spec. Missing the version means skip the publish entirely."""
    bridge, publisher, _ = _bridge()

    bridge.on_function_deployed(Event(
        event_type=FUNCTION_DEPLOYED_EVENT, payload={"function_id": "add"}, timestamp=100.0,
    ))

    assert publisher.published == []


def test_on_function_deploy_failed_from_container_crashed():
    bridge, publisher, _ = _bridge()

    bridge.on_function_deploy_failed(Event(
        event_type=CONTAINER_CRASHED_EVENT,
        payload={"function_id": "add", "version": 1, "service_name": "svc", "error_message": "timed out"},
        timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_DEPLOY_FAILED
    assert data["runtime_type"] == "container"
    assert data["failure"]["message"] == "timed out"


def test_on_function_stopped_forwards_reason():
    bridge, publisher, _ = _bridge(runtime_spec=RuntimeSpec(type="process"))

    bridge.on_function_stopped(Event(
        event_type=FUNCTION_STOPPED_EVENT,
        payload={"function_id": "add", "version": 1, "reason": "idle_ttl"},
        timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_STOPPED
    assert data["reason"] == "idle_ttl"
    assert data["runtime_type"] == "process"


def test_on_function_crashed_forwards_runtime_type():
    bridge, publisher, _ = _bridge(runtime_spec=RuntimeSpec(type="process"))

    bridge.on_function_crashed(Event(
        event_type=FUNCTION_CRASHED_EVENT,
        payload={"function_id": "add", "version": 1},
        timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_CRASHED
    assert data["function_id"] == "add"
    assert data["runtime_type"] == "process"


def test_on_function_stopped_skips_publish_when_version_unknown():
    bridge, publisher, _ = _bridge()

    bridge.on_function_stopped(Event(
        event_type=FUNCTION_STOPPED_EVENT, payload={"function_id": "add", "reason": "idle_ttl"}, timestamp=100.0,
    ))

    assert publisher.published == []


def test_on_function_crashed_skips_publish_when_version_unknown():
    bridge, publisher, _ = _bridge()

    bridge.on_function_crashed(Event(
        event_type=FUNCTION_CRASHED_EVENT, payload={"function_id": "add"}, timestamp=100.0,
    ))

    assert publisher.published == []


def test_on_function_build_event_forwards_started_completed_failed():
    bridge, publisher, _ = _bridge()

    bridge.on_function_build_event(Event(
        event_type=FUNCTION_BUILD_STARTED_EVENT,
        payload={"function_id": None, "python_version": "3.11", "image_tag": "axo-runner:py3.11"},
        timestamp=100.0,
    ))
    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_BUILD_STARTED
    assert data["runtime_type"] == "container"

    publisher.published.clear()
    bridge.on_function_build_event(Event(
        event_type=FUNCTION_BUILD_COMPLETED_EVENT,
        payload={
            "function_id": None, "python_version": "3.11", "image_tag": "axo-runner:py3.11",
            "duration_ms": 42.0,
        },
        timestamp=100.0,
    ))
    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_BUILD_COMPLETED
    assert data["duration_ms"] == 42.0

    publisher.published.clear()
    bridge.on_function_build_event(Event(
        event_type=FUNCTION_BUILD_FAILED_EVENT,
        payload={
            "function_id": None, "python_version": "3.11", "image_tag": "axo-runner:py3.11",
            "error_message": "build broke",
        },
        timestamp=100.0,
    ))
    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_BUILD_FAILED
    assert data["failure"]["message"] == "build broke"


def test_on_function_updated_forwards_current_record_env_vars_and_params_schema():
    bridge, publisher, registry = _bridge(runtime_spec=RuntimeSpec(type="process"))
    key = StorageKey(id="add", version=1, alias="add")
    registry.update(key, now=150.0, env_vars={"A": "1"})

    bridge.on_function_updated(Event(
        event_type="FUNCTION_UPDATED", payload={"function_id": "add", "version": 1}, timestamp=150.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_UPDATED
    assert data["function_id"] == "add"
    assert data["version"] == 1
    assert data["env_vars"] == {"A": "1"}


def test_on_function_deleted_and_delete_failed():
    bridge, publisher, _ = _bridge()

    bridge.on_function_deleted(Event(
        event_type=FUNCTION_DELETED_EVENT, payload={"function_id": "add", "version": 1}, timestamp=100.0,
    ))
    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_DELETED
    assert data["function_id"] == "add"

    publisher.published.clear()
    bridge.on_function_delete_failed(Event(
        event_type=FUNCTION_DELETE_FAILED_EVENT,
        payload={
            "function_id": "add", "version": 1,
            "failure": {
                "error_class": "STORAGE_ERROR", "error_code": 8000, "component": "function_registry",
                "message": "boom", "traceback": None, "is_transient": False,
            },
        },
        timestamp=100.0,
    ))
    event_type, data = publisher.published[0]
    assert event_type == event_models.FUNCTION_DELETE_FAILED
    assert data["failure"]["message"] == "boom"


def test_on_job_queued_forwards_job_queued():
    bridge, publisher, _ = _bridge()

    bridge.on_job_queued(Event(
        event_type="JOB_SUBMITTED", payload={"job_id": "job1", "function_id": "add"}, timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.JOB_QUEUED
    assert data["job_id"] == "job1"


def test_on_job_started_forwards_job_started_and_function_activated():
    bridge, publisher, _ = _bridge(runtime_spec=RuntimeSpec(type="process"))

    bridge.on_job_started(Event(
        event_type=JOB_STARTED_EVENT,
        payload={"job_id": "job1", "function_id": "add", "function_version": 1, "params": {"a": 1}},
        timestamp=100.0,
    ))

    assert len(publisher.published) == 2
    job_event_type, job_data = publisher.published[0]
    fn_event_type, fn_data = publisher.published[1]
    assert job_event_type == event_models.JOB_STARTED
    assert job_data["job_id"] == "job1"
    assert job_data["version"] == 1
    assert job_data["params"] == {"a": 1}
    assert fn_event_type == event_models.FUNCTION_ACTIVATED
    assert fn_data["job_id"] == "job1"
    assert fn_data["version"] == 1
    assert fn_data["runtime_type"] == "process"


def test_on_job_started_trusts_payload_version_over_latest_registered():
    """Regression test: re-registering a function with a newer version while
    an older-version worker still has a job in flight must not make the
    bridge report the newer version for that in-flight job -- it must trust
    the version the payload says actually picked up the job, not whatever
    the registry currently considers "latest"."""
    bridge, publisher, registry = _bridge(runtime_spec=RuntimeSpec(type="process"))
    registry.register(function_id="add", name="add", code=b"", now=200.0, runtime_spec=RuntimeSpec(type="process"))

    bridge.on_job_started(Event(
        event_type=JOB_STARTED_EVENT,
        payload={"job_id": "job1", "function_id": "add", "function_version": 1, "params": {}},
        timestamp=100.0,
    ))

    _job_event_type, job_data = publisher.published[0]
    fn_event_type, fn_data = publisher.published[1]
    assert job_data["version"] == 1
    assert fn_event_type == event_models.FUNCTION_ACTIVATED
    assert fn_data["version"] == 1


def test_on_job_started_still_forwards_job_started_but_skips_function_activated_when_version_unknown():
    """Regression test: JobStarted tolerates an unknown version (it always
    gets forwarded, e.g. so the job telemetry timeline stays complete), but
    FunctionActivated requires one -- previously coerced missing to a fake
    0, now skipped instead of forwarding a phantom function version."""
    bridge, publisher, _ = _bridge()

    bridge.on_job_started(Event(
        event_type=JOB_STARTED_EVENT,
        payload={"job_id": "job1", "function_id": "add", "params": {}},
        timestamp=100.0,
    ))

    assert len(publisher.published) == 1
    event_type, data = publisher.published[0]
    assert event_type == event_models.JOB_STARTED
    assert data["version"] is None


def test_on_job_finished_forwards_job_completed_and_function_deactivated():
    results = InMemoryStorageBackend()
    results.put(StorageKey(id="job1"), FunctionResult(job_id="job1", ok=True, output={"value": 42, "type": "json"}))
    bridge, publisher, _ = _bridge(results=results)

    bridge.on_job_finished(Event(
        event_type="JOB_COMPLETED",
        payload={"job_id": "job1", "function_id": "add", "function_version": 1},
        timestamp=200.0,
    ))

    assert len(publisher.published) == 2
    job_event_type, job_data = publisher.published[0]
    fn_event_type, fn_data = publisher.published[1]
    assert job_event_type == event_models.JOB_COMPLETED
    assert fn_event_type == event_models.FUNCTION_DEACTIVATED
    assert fn_data["state"] == "COMPLETED"


def test_on_job_finished_forwards_duration_ms_and_trusted_version():
    results = InMemoryStorageBackend()
    results.put(StorageKey(id="job1"), FunctionResult(job_id="job1", ok=True, output={"value": 42, "type": "json"}))
    bridge, publisher, registry = _bridge(results=results)
    registry.register(function_id="add", name="add", code=b"", now=200.0)  # newer version now registered

    bridge.on_job_finished(Event(
        event_type="JOB_COMPLETED",
        payload={"job_id": "job1", "function_id": "add", "function_version": 1, "duration_ms": 42.5},
        timestamp=200.0,
    ))

    job_event_type, job_data = publisher.published[0]
    fn_event_type, fn_data = publisher.published[1]
    assert job_event_type == event_models.JOB_COMPLETED
    assert job_data["duration_ms"] == 42.5
    assert fn_event_type == event_models.FUNCTION_DEACTIVATED
    assert fn_data["version"] == 1  # trusts the payload, not the newer registered version


def test_on_job_finished_still_forwards_job_completed_but_skips_function_deactivated_when_version_unknown():
    results = InMemoryStorageBackend()
    results.put(StorageKey(id="job1"), FunctionResult(job_id="job1", ok=True, output={"value": 42, "type": "json"}))
    bridge, publisher, _ = _bridge(results=results)

    bridge.on_job_finished(Event(
        event_type="JOB_COMPLETED", payload={"job_id": "job1", "function_id": "add"}, timestamp=200.0,
    ))

    assert len(publisher.published) == 1
    event_type, _data = publisher.published[0]
    assert event_type == event_models.JOB_COMPLETED


def test_on_job_finished_forwards_job_failed_with_failure_detail():
    results = InMemoryStorageBackend()
    results.put(StorageKey(id="job2"), FunctionResult(job_id="job2", ok=False, error="boom"))
    bridge, publisher, _ = _bridge(results=results)

    bridge.on_job_finished(Event(
        event_type="JOB_FAILED",
        payload={"job_id": "job2", "function_id": "add", "function_version": 1},
        timestamp=200.0,
    ))

    job_event_type, job_data = publisher.published[0]
    fn_event_type, fn_data = publisher.published[1]
    assert job_event_type == event_models.JOB_FAILED
    assert job_data["failure"]["message"] == "boom"
    assert fn_event_type == event_models.FUNCTION_DEACTIVATED
    assert fn_data["state"] == "FAILED"


def test_on_bucket_registered_forwards_data_bucket_created():
    bridge, publisher, _ = _bridge()

    bridge.on_bucket_registered(Event(
        event_type="BUCKET_REGISTERED",
        payload={"name": "mybucket", "quota_bytes": 1024, "created_at": 100.0},
        timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.DATA_BUCKET_CREATED
    assert data["name"] == "mybucket"
    assert data["quota_bytes"] == 1024
    assert data["endpoint_id"] == "n0"


def test_on_data_registered_forwards_data_registered():
    bridge, publisher, _ = _bridge()

    bridge.on_data_registered(Event(
        event_type="DATA_REGISTERED",
        payload={
            "data_id": "mybucket/df1", "version": 1, "total_chunks": 2,
            "format": "raw", "kind": "fs", "total_size": 8,
        },
        timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.DATA_REGISTERED
    assert data["name"] == "mybucket/df1"
    assert data["version"] == 1
    assert data["format"] == "raw"
    assert data["kind"] == "fs"
    assert data["total_size"] == 8
    assert data["total_chunks"] == 2


def test_on_data_upload_completed_forwards_data_upload_completed():
    bridge, publisher, _ = _bridge()

    bridge.on_data_upload_completed(Event(
        event_type="DATA_UPLOAD_COMPLETED",
        payload={"data_id": "mybucket/df1", "version": 1},
        timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.DATA_UPLOAD_COMPLETED
    assert data["name"] == "mybucket/df1"
    assert data["version"] == 1
    assert data["endpoint_id"] == "n0"


def test_on_data_deleted_forwards_data_deleted():
    bridge, publisher, _ = _bridge()

    bridge.on_data_deleted(Event(
        event_type="DATA_DELETED",
        payload={"data_id": "mybucket/df1", "version": 1},
        timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.DATA_DELETED
    assert data["name"] == "mybucket/df1"
    assert data["version"] == 1
    assert data["endpoint_id"] == "n0"


def test_on_leader_elected_forwards_leader_elected():
    bridge, publisher, _ = _bridge()

    bridge.on_leader_elected(Event(
        event_type="LEADER_ELECTED", payload={"leader_ids": ["n0"], "term": 3}, timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.LEADER_ELECTED
    assert data["term"] == 3
    assert data["leader_ids"] == ["n0"]


def test_on_consensus_view_changed_forwards_consensus_view_changed():
    bridge, publisher, _ = _bridge()

    bridge.on_consensus_view_changed(Event(
        event_type="CONSENSUS_VIEW_CHANGED",
        payload={"term": 3, "was_leader": False, "is_leader": True, "leader_ids": ["n0"]},
        timestamp=100.0,
    ))

    event_type, data = publisher.published[0]
    assert event_type == event_models.CONSENSUS_VIEW_CHANGED
    assert data["is_leader"] is True
    assert data["was_leader"] is False


def test_on_cluster_quorum_event_forwards_lost_restored_degraded():
    bridge, publisher, _ = _bridge()

    bridge.on_cluster_quorum_event(Event(
        event_type=CLUSTER_QUORUM_LOST_EVENT,
        payload={"term": 1, "member_count": 1, "quorum_size": 2}, timestamp=100.0,
    ))
    event_type, data = publisher.published[0]
    assert event_type == event_models.CLUSTER_QUORUM_LOST

    publisher.published.clear()
    bridge.on_cluster_quorum_event(Event(
        event_type=CLUSTER_QUORUM_RESTORED_EVENT,
        payload={"term": 1, "member_count": 2, "quorum_size": 2}, timestamp=100.0,
    ))
    event_type, data = publisher.published[0]
    assert event_type == event_models.CLUSTER_QUORUM_RESTORED

    publisher.published.clear()
    bridge.on_cluster_quorum_event(Event(
        event_type=CLUSTER_DEGRADED_EVENT,
        payload={"term": 1, "member_count": 2, "quorum_size": 2, "evicted_peer_id": "n1"},
        timestamp=100.0,
    ))
    event_type, data = publisher.published[0]
    assert event_type == event_models.CLUSTER_DEGRADED
    assert data["evicted_peer_id"] == "n1"
