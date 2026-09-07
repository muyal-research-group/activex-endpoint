import threading

import zmq

from axo_shared import wire
from axo_shared.events import models
from axo_shared.protocol import CommandResult


def _run_fake_endpoint(reply_ok, error_message="", metadata=None):
    """Binds its own ephemeral port directly (no separate probe-then-rebind
    step -- that pattern races under rapid successive binds) and returns the
    resolved address alongside the serving thread/captured command."""
    ctx = zmq.Context.instance()
    router = ctx.socket(zmq.ROUTER)
    router.setsockopt(zmq.RCVTIMEO, 3000)
    router.bind("tcp://127.0.0.1:0")
    address = router.getsockopt(zmq.LAST_ENDPOINT).decode("utf-8")

    captured = {}

    def _serve():
        frames = router.recv_multipart()
        identity, body = frames[0], frames[1:]
        command = wire.decode_command(body).unwrap()
        captured["command"] = command
        result = CommandResult(ok=reply_ok, error=error_message, metadata=metadata or {})
        router.send_multipart([identity, *wire.encode_command_result(result)])
        router.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return address, thread, captured


def test_get_job_returns_404_when_missing(client):
    response = client.get("/jobs/missing")
    assert response.status_code == 404


def test_get_job_returns_full_record(client, kurrent_appender):
    queued = models.JobQueued(
        endpoint_id="n0", job_id="job1", function_id="add", version=1, params={"a": 1, "b": 2},
    )
    kurrent_appender.append_to_stream("activity-add", models.JOB_QUEUED, queued.model_dump(mode="json"))

    response = client.get("/jobs/job1")
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job1"
    assert body["function_id"] == "add"
    assert body["status"] == "QUEUED"
    assert body["function_version"] == 1
    assert body["params"] == {"a": 1, "b": 2}


def test_get_job_reflects_lifecycle_updates(client, kurrent_appender):
    queued = models.JobQueued(endpoint_id="n0", job_id="job2", function_id="add", version=1)
    kurrent_appender.append_to_stream("activity-add", models.JOB_QUEUED, queued.model_dump(mode="json"))

    completed = models.JobCompleted(endpoint_id="n0", job_id="job2", function_id="add", duration_ms=99.5)
    kurrent_appender.append_to_stream("activity-add", models.JOB_COMPLETED, completed.model_dump(mode="json"))

    response = client.get("/jobs/job2")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["duration_ms"] == 99.5


def test_list_jobs_for_function_returns_newest_first(client, kurrent_appender):
    older = models.JobQueued(endpoint_id="n0", job_id="job-a", function_id="add", version=1)
    kurrent_appender.append_to_stream("activity-add", models.JOB_QUEUED, older.model_dump(mode="json"))
    newer = models.JobQueued(endpoint_id="n0", job_id="job-b", function_id="add", version=1)
    kurrent_appender.append_to_stream("activity-add", models.JOB_QUEUED, newer.model_dump(mode="json"))

    response = client.get("/functions/add/jobs")
    assert response.status_code == 200
    job_ids = [j["job_id"] for j in response.json()]
    assert job_ids == ["job-b", "job-a"]


def test_list_jobs_for_function_filters_by_version(client, kurrent_appender):
    v1 = models.JobQueued(endpoint_id="n0", job_id="job-v1", function_id="add", version=1)
    kurrent_appender.append_to_stream("activity-add", models.JOB_QUEUED, v1.model_dump(mode="json"))
    v2 = models.JobQueued(endpoint_id="n0", job_id="job-v2", function_id="add", version=2)
    kurrent_appender.append_to_stream("activity-add", models.JOB_QUEUED, v2.model_dump(mode="json"))

    response = client.get("/functions/add/jobs", params={"version": 2})
    assert response.status_code == 200
    job_ids = [j["job_id"] for j in response.json()]
    assert job_ids == ["job-v2"]


def test_submit_job_forwards_command_and_relays_success(client, collections):
    address, thread, captured = _run_fake_endpoint(reply_ok=True, metadata={"job_id": "job1", "status": "QUEUED"})
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})

    response = client.post(
        "/endpoints/127.0.0.1/jobs",
        json={"function_id": "add-hash", "function_name": "add", "function_version": 1, "params": {"a": 1}},
    )
    thread.join(timeout=2.0)

    assert response.status_code == 200
    body = response.json()
    assert body["endpoint_id"] == "127.0.0.1"
    assert body["job_id"] == "job1"
    assert body["status"] == "QUEUED"

    command = captured["command"]
    assert command.operation == wire.JOB_SUBMIT
    assert command.envelope == {
        "function_id": "add-hash", "function_name": "add", "function_version": 1, "params": {"a": 1},
    }


def test_submit_job_relays_rejection_as_409(client, collections):
    address, thread, _ = _run_fake_endpoint(reply_ok=False, error_message="invalid params")
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})

    response = client.post(
        "/endpoints/127.0.0.1/jobs",
        json={"function_id": "add-hash", "function_version": 1, "params": {}},
    )
    thread.join(timeout=2.0)

    assert response.status_code == 409
    assert response.json()["detail"] == "invalid params"


def test_submit_job_returns_404_for_unknown_endpoint(client):
    response = client.post(
        "/endpoints/missing/jobs",
        json={"function_id": "add-hash", "function_version": 1, "params": {}},
    )
    assert response.status_code == 404


def test_submit_function_job_routes_to_ve_leader(client, collections, kurrent_appender):
    address, thread, captured = _run_fake_endpoint(reply_ok=True, metadata={"job_id": "job1", "status": "QUEUED"})

    # A VE doc must already exist for set_leader_endpoint_id() to take (it's
    # a conditional update, never an upsert).
    kurrent_appender.append_to_stream(
        "virtual-environments-ve-1", models.VIRTUAL_ENV_CREATED,
        models.VirtualEnvironmentCreated(
            virtual_environment_id="ve-1", name="ve1", owner_user_id="alice",
            resource_quota=models.ResourceQuota(cpu=1, ram=1, disk=1),
        ).model_dump(mode="json"),
    )
    kurrent_appender.append_to_stream(
        "functions-add:1", models.FUNCTION_REGISTERED,
        models.FunctionRegistered(
            endpoint_id="127.0.0.1", virtual_environment_id="ve-1", function_id="add-hash", version=1, name="add",
        ).model_dump(mode="json"),
    )
    # Two endpoints assigned to the VE -- n1 is merely most-recently-seen (and
    # never actually dialed, so an unreachable placeholder bind is fine),
    # 127.0.0.1 is the elected leader and must win over that recency pick.
    # resolve_rpc_uri() reconstructs the connect host from endpoint_id itself
    # (never from the stored router_bind's host -- see its docstring), so the
    # leader's endpoint_id must literally be the fake router's real host.
    for endpoint_id, bind in (("127.0.0.1", address), ("n1", "tcp://127.0.0.1:1")):
        kurrent_appender.append_to_stream(
            f"endpoints-{endpoint_id}", models.ENDPOINT_STARTED,
            models.EndpointStarted(endpoint_id=endpoint_id, router_bind=bind, pub_bind="tcp://127.0.0.1:2").model_dump(mode="json"),
        )
        kurrent_appender.append_to_stream(
            f"endpoints-{endpoint_id}", models.ENDPOINT_VIRTUAL_ENV_ASSIGNED,
            models.EndpointVirtualEnvironmentAssigned(endpoint_id=endpoint_id, virtual_environment_id="ve-1").model_dump(mode="json"),
        )
    kurrent_appender.append_to_stream(
        "consensus-1", models.LEADER_ELECTED,
        models.LeaderElected(endpoint_id="127.0.0.1", leader_ids=["127.0.0.1"], term=1).model_dump(mode="json"),
    )

    response = client.post("/functions/add-hash/1/jobs", json={"params": {"a": 1}})
    thread.join(timeout=2.0)

    assert response.status_code == 200
    body = response.json()
    assert body["endpoint_id"] == "127.0.0.1"
    assert body["job_id"] == "job1"

    command = captured["command"]
    assert command.operation == wire.JOB_SUBMIT
    assert command.envelope["function_id"] == "add-hash"
    assert command.envelope["function_version"] == 1
    assert command.envelope["params"] == {"a": 1}


def test_submit_function_job_falls_back_to_most_recently_seen_endpoint(client, collections, kurrent_appender):
    address, thread, captured = _run_fake_endpoint(reply_ok=True, metadata={"job_id": "job2", "status": "QUEUED"})

    kurrent_appender.append_to_stream(
        "functions-add:1", models.FUNCTION_REGISTERED,
        models.FunctionRegistered(
            endpoint_id="127.0.0.1", virtual_environment_id="ve-1", function_id="add-hash", version=1, name="add",
        ).model_dump(mode="json"),
    )
    kurrent_appender.append_to_stream(
        "endpoints-127.0.0.1", models.ENDPOINT_STARTED,
        models.EndpointStarted(endpoint_id="127.0.0.1", router_bind=address, pub_bind="tcp://127.0.0.1:2").model_dump(mode="json"),
    )
    kurrent_appender.append_to_stream(
        "endpoints-127.0.0.1", models.ENDPOINT_VIRTUAL_ENV_ASSIGNED,
        models.EndpointVirtualEnvironmentAssigned(endpoint_id="127.0.0.1", virtual_environment_id="ve-1").model_dump(mode="json"),
    )
    # No LeaderElected at all -- no VE doc even exists yet, must fall back.

    response = client.post("/functions/add-hash/1/jobs", json={"params": {}})
    thread.join(timeout=2.0)

    assert response.status_code == 200
    assert response.json()["endpoint_id"] == "127.0.0.1"


def test_submit_function_job_returns_404_for_unknown_function(client):
    response = client.post("/functions/missing/1/jobs", json={"params": {}})
    assert response.status_code == 404


def test_poll_job_result_relays_node_response(client, collections):
    address, thread, captured = _run_fake_endpoint(
        reply_ok=True,
        metadata={"job_id": "job1", "status": "COMPLETED", "result_ok": True, "values": {"value": 3}, "error": None},
    )
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})

    response = client.get("/endpoints/127.0.0.1/jobs/job1")
    thread.join(timeout=2.0)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["values"] == {"value": 3}

    command = captured["command"]
    assert command.operation == wire.JOB_RESULT
    assert command.envelope == {"job_id": "job1"}
