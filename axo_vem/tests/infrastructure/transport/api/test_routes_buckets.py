import threading

import zmq

from axo_shared import wire
from axo_shared.events import models
from axo_shared.protocol import CommandResult


def _run_fake_endpoint(replies):
    """Binds its own ephemeral port directly (no separate probe-then-rebind
    step -- that pattern races under rapid successive binds) and serves one
    reply per received command, in order -- lets a test stand in for a real
    node across a DATA_REGISTER + N DATA_CHUNK_PUT sequence. Returns the
    resolved address alongside the serving thread/captured commands."""
    ctx = zmq.Context.instance()
    router = ctx.socket(zmq.ROUTER)
    router.setsockopt(zmq.RCVTIMEO, 3000)
    router.bind("tcp://127.0.0.1:0")
    address = router.getsockopt(zmq.LAST_ENDPOINT).decode("utf-8")

    captured = []

    def _serve():
        for reply_ok, error_message, metadata in replies:
            frames = router.recv_multipart()
            identity, body = frames[0], frames[1:]
            command = wire.decode_command(body).unwrap()
            captured.append(command)
            result = CommandResult(ok=reply_ok, error=error_message, metadata=metadata or {})
            router.send_multipart([identity, *wire.encode_command_result(result)])
        router.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return address, thread, captured


def test_create_bucket_forwards_command_and_relays_success(client, collections):
    address, thread, captured = _run_fake_endpoint(
        [(True, "", {"name": "mybucket", "quota_bytes": 1024, "created_at": 100.0})],
    )
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})

    response = client.post("/endpoints/127.0.0.1/buckets", json={"name": "mybucket", "quota_bytes": 1024})
    thread.join(timeout=2.0)

    assert response.status_code == 200
    body = response.json()
    assert body["endpoint_id"] == "127.0.0.1"
    assert body["name"] == "mybucket"

    command = captured[0]
    assert command.operation == wire.BUCKET_REGISTER
    assert command.envelope == {"name": "mybucket", "quota_bytes": 1024}


def test_create_bucket_relays_rejection_as_409(client, collections):
    address, thread, _ = _run_fake_endpoint([(False, "bucket already exists", None)])
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})

    response = client.post("/endpoints/127.0.0.1/buckets", json={"name": "mybucket", "quota_bytes": 1024})
    thread.join(timeout=2.0)

    assert response.status_code == 409
    assert response.json()["detail"] == "bucket already exists"


def test_create_bucket_returns_404_for_unknown_endpoint(client):
    response = client.post("/endpoints/missing/buckets", json={"name": "mybucket", "quota_bytes": 1024})
    assert response.status_code == 404


def test_upload_data_registers_then_chunks_via_leader(client, collections):
    # No consensus doc reported yet -- must fall back to the originally
    # targeted endpoint for the DATA_CHUNK_PUT relay too.
    address, thread, captured = _run_fake_endpoint([
        (True, "", {"data_id": "mybucket/df1", "version": 1, "total_chunks": 1, "leader_rpc_uri": "tcp://0.0.0.0:5555"}),
        (True, "", {"data_id": "mybucket/df1", "version": 1, "received_count": 1, "total_chunks": 1, "complete": True}),
    ])
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})

    response = client.post(
        "/endpoints/127.0.0.1/buckets/mybucket/data",
        data={"key": "df1", "version": "1", "format": "raw", "kind": "fs"},
        files={"file": ("df1.bin", b"hello", "application/octet-stream")},
    )
    thread.join(timeout=2.0)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "mybucket/df1"
    assert body["total_size"] == 5
    assert body["total_chunks"] == 1

    register_command, chunk_command = captured
    assert register_command.operation == wire.DATA_REGISTER
    assert register_command.envelope["name"] == "mybucket/df1"
    assert register_command.envelope["total_size"] == 5
    assert chunk_command.operation == wire.DATA_CHUNK_PUT
    assert chunk_command.envelope == {"name": "mybucket/df1", "version": 1, "chunk_index": 0}
    assert chunk_command.payload == b"hello"


def test_upload_data_targets_the_resolved_leader_for_chunk_puts(client, collections):
    """When a consensus view IS reported, DATA_CHUNK_PUT must target the
    leader's own endpoint -- not the (possibly-follower) endpoint the
    upload was originally addressed to."""
    follower_address, follower_thread, follower_captured = _run_fake_endpoint([
        (True, "", {"data_id": "mybucket/df1", "version": 1, "total_chunks": 1, "leader_rpc_uri": "tcp://0.0.0.0:5555"}),
    ])
    leader_address, leader_thread, leader_captured = _run_fake_endpoint([
        (True, "", {"data_id": "mybucket/df1", "version": 1, "received_count": 1, "total_chunks": 1, "complete": True}),
    ])

    # resolve_rpc_uri derives the connect HOST from endpoint_id itself (by
    # design -- matches Docker DNS in production), so both ids here must be
    # locally resolvable hostnames, not placeholder strings like "leader".
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": follower_address})
    collections.endpoints.insert_one({"_id": "localhost", "router_bind": leader_address})
    collections.consensus.insert_one({"_id": 1, "term": 1, "leader_ids": ["localhost"]})

    response = client.post(
        "/endpoints/127.0.0.1/buckets/mybucket/data",
        data={"key": "df1", "version": "1"},
        files={"file": ("df1.bin", b"hi", "application/octet-stream")},
    )
    follower_thread.join(timeout=2.0)
    leader_thread.join(timeout=2.0)

    assert response.status_code == 200
    assert follower_captured[0].operation == wire.DATA_REGISTER
    assert leader_captured[0].operation == wire.DATA_CHUNK_PUT


def test_upload_data_returns_404_for_unknown_endpoint(client):
    response = client.post(
        "/endpoints/missing/buckets/mybucket/data",
        data={"key": "df1", "version": "1"},
        files={"file": ("df1.bin", b"hi", "application/octet-stream")},
    )
    assert response.status_code == 404


def test_list_buckets_reports_quota_usage(client, kurrent_appender):
    created = models.DataBucketCreated(endpoint_id="n0", name="mybucket", quota_bytes=1024)
    kurrent_appender.append_to_stream("buckets-mybucket", models.DATA_BUCKET_CREATED, created.model_dump(mode="json"))
    registered = models.DataRegistered(
        endpoint_id="n0", name="mybucket/df1", version=1, format="raw", kind="fs", total_size=8, total_chunks=2,
    )
    kurrent_appender.append_to_stream("buckets-mybucket", models.DATA_REGISTERED, registered.model_dump(mode="json"))

    response = client.get("/buckets")
    assert response.status_code == 200
    buckets = response.json()
    assert len(buckets) == 1
    assert buckets[0]["name"] == "mybucket"
    assert buckets[0]["quota_bytes"] == 1024
    assert buckets[0]["used_bytes"] == 8


def test_get_bucket_returns_items(client, kurrent_appender):
    created = models.DataBucketCreated(endpoint_id="n0", name="mybucket", quota_bytes=1024)
    kurrent_appender.append_to_stream("buckets-mybucket", models.DATA_BUCKET_CREATED, created.model_dump(mode="json"))
    registered = models.DataRegistered(
        endpoint_id="n0", name="mybucket/df1", version=1, format="raw", kind="fs", total_size=8, total_chunks=2,
    )
    kurrent_appender.append_to_stream("buckets-mybucket", models.DATA_REGISTERED, registered.model_dump(mode="json"))

    response = client.get("/buckets/mybucket")
    assert response.status_code == 200
    body = response.json()
    assert body["used_bytes"] == 8
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "mybucket/df1"


def test_data_item_is_pending_until_upload_completed_event_lands(client, kurrent_appender):
    created = models.DataBucketCreated(endpoint_id="n0", name="mybucket", quota_bytes=1024)
    kurrent_appender.append_to_stream("buckets-mybucket", models.DATA_BUCKET_CREATED, created.model_dump(mode="json"))
    registered = models.DataRegistered(
        endpoint_id="n0", name="mybucket/df1", version=1, format="raw", kind="fs", total_size=8, total_chunks=2,
    )
    kurrent_appender.append_to_stream("buckets-mybucket", models.DATA_REGISTERED, registered.model_dump(mode="json"))

    pending_body = client.get("/buckets/mybucket").json()
    assert pending_body["items"][0]["status"] == "pending"

    completed = models.DataUploadCompleted(endpoint_id="n0", name="mybucket/df1", version=1)
    kurrent_appender.append_to_stream(
        "buckets-mybucket", models.DATA_UPLOAD_COMPLETED, completed.model_dump(mode="json"),
    )

    ready_body = client.get("/buckets/mybucket").json()
    assert ready_body["items"][0]["status"] == "ready"


def test_download_data_streams_reassembled_bytes(client, collections, kurrent_appender):
    registered = models.DataRegistered(
        endpoint_id="n0", name="mybucket/df1", version=1,
        format="raw", kind="fs", total_size=8, total_chunks=2,
    )
    kurrent_appender.append_to_stream("buckets-mybucket", models.DATA_REGISTERED, registered.model_dump(mode="json"))
    completed = models.DataUploadCompleted(endpoint_id="n0", name="mybucket/df1", version=1)
    kurrent_appender.append_to_stream(
        "buckets-mybucket", models.DATA_UPLOAD_COMPLETED, completed.model_dump(mode="json"),
    )

    address, thread, captured = _run_fake_endpoint([
        (True, "", {"name": "mybucket/df1", "version": 1, "chunk_index": 0}),
        (True, "", {"name": "mybucket/df1", "version": 1, "chunk_index": 1}),
    ])
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})

    response = client.get("/endpoints/127.0.0.1/buckets/mybucket/data/df1/1/download")
    thread.join(timeout=2.0)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="df1"'
    assert len(captured) == 2
    assert captured[0].envelope == {"name": "mybucket/df1", "version": 1, "chunk_index": 0}
    assert captured[1].envelope == {"name": "mybucket/df1", "version": 1, "chunk_index": 1}


def test_download_data_returns_404_when_data_not_registered(client, collections):
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": "tcp://127.0.0.1:1"})
    response = client.get("/endpoints/127.0.0.1/buckets/mybucket/data/missing/1/download")
    assert response.status_code == 404


def test_download_data_returns_409_while_still_pending(client, collections, kurrent_appender):
    registered = models.DataRegistered(
        endpoint_id="n0", name="mybucket/df1", version=1,
        format="raw", kind="fs", total_size=8, total_chunks=2,
    )
    kurrent_appender.append_to_stream("buckets-mybucket", models.DATA_REGISTERED, registered.model_dump(mode="json"))
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": "tcp://127.0.0.1:1"})

    response = client.get("/endpoints/127.0.0.1/buckets/mybucket/data/df1/1/download")
    assert response.status_code == 409


def test_delete_data_forwards_command_and_relays_success(client, collections):
    address, thread, captured = _run_fake_endpoint([(True, "", {"data_id": "mybucket/df1", "version": 1})])
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})

    response = client.delete("/endpoints/127.0.0.1/buckets/mybucket/data/df1/1")
    thread.join(timeout=2.0)

    assert response.status_code == 200
    body = response.json()
    assert body == {"endpoint_id": "127.0.0.1", "bucket": "mybucket", "name": "mybucket/df1", "version": 1}

    command = captured[0]
    assert command.operation == wire.DATA_DELETE
    assert command.envelope == {"name": "mybucket/df1", "version": 1}


def test_delete_data_relays_rejection_as_409(client, collections):
    address, thread, _ = _run_fake_endpoint([(False, "df1:1 is not registered", None)])
    collections.endpoints.insert_one({"_id": "127.0.0.1", "router_bind": address})

    response = client.delete("/endpoints/127.0.0.1/buckets/mybucket/data/df1/1")
    thread.join(timeout=2.0)

    assert response.status_code == 409
    assert response.json()["detail"] == "df1:1 is not registered"


def test_delete_data_returns_404_for_unknown_endpoint(client):
    response = client.delete("/endpoints/missing/buckets/mybucket/data/df1/1")
    assert response.status_code == 404


def test_get_bucket_returns_404_when_missing(client):
    response = client.get("/buckets/missing")
    assert response.status_code == 404
