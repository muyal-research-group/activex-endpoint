import mongomock
from starlette.testclient import TestClient

from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository
from axo_vem.infrastructure.database.mongo.collections import ReadCollections
from axo_vem.infrastructure.transport.api.app import create_app
from axo_vem.infrastructure.transport.ws.broadcaster import Broadcaster


def _app_with_broadcaster(broadcaster: Broadcaster):
    db = mongomock.MongoClient()["test"]
    collections = ReadCollections(endpoints=db["endpoints"], functions=db["functions"], consensus=db["consensus"])
    return create_app(
        collections=collections,
        activity_repository=MongoActivityRepository(db["unified_activity"]),
        broadcaster=broadcaster,
    )


def test_ws_buckets_route_delivers_a_broadcast_message():
    broadcaster = Broadcaster()
    app = _app_with_broadcaster(broadcaster)

    # Must enter TestClient itself as a context manager -- that's what
    # actually runs the ASGI lifespan (startup/shutdown) events, and
    # bind_loop() only ever happens inside this app's startup hook. Without
    # it, broadcaster._loop stays None and broadcast() silently no-ops,
    # hanging the receive_json() below forever.
    with TestClient(app) as client, client.websocket_connect("/ws/buckets") as websocket:
        broadcaster.broadcast("buckets", {"bucket": "b1", "name": "b1/df1", "version": 1, "status": "pending"})
        message = websocket.receive_json()

    assert message == {"bucket": "b1", "name": "b1/df1", "version": 1, "status": "pending"}


def test_ws_endpoints_route_delivers_a_broadcast_message():
    broadcaster = Broadcaster()
    app = _app_with_broadcaster(broadcaster)

    with TestClient(app) as client, client.websocket_connect("/ws/endpoints") as websocket:
        broadcaster.broadcast("endpoints", {"endpoint_id": "n0", "available": True, "cpu_percent": 5.0})
        message = websocket.receive_json()

    assert message == {"endpoint_id": "n0", "available": True, "cpu_percent": 5.0}


def test_ws_functions_route_delivers_a_broadcast_message():
    broadcaster = Broadcaster()
    app = _app_with_broadcaster(broadcaster)

    with TestClient(app) as client, client.websocket_connect("/ws/functions") as websocket:
        broadcaster.broadcast("functions", {"function_id": "add", "version": 1, "name": "add"})
        message = websocket.receive_json()

    assert message == {"function_id": "add", "version": 1, "name": "add"}


def test_ws_endpoint_scoped_route_only_receives_its_own_topic():
    broadcaster = Broadcaster()
    app = _app_with_broadcaster(broadcaster)

    with TestClient(app) as client, client.websocket_connect("/ws/endpoints/n0") as websocket:
        # A fleet-wide broadcast on a different endpoint's scoped topic must
        # not reach this connection.
        broadcaster.broadcast("endpoints:n1", {"endpoint_id": "n1", "available": True})
        broadcaster.broadcast("endpoints:n0", {"endpoint_id": "n0", "available": True, "cpu_percent": 1.0})
        message = websocket.receive_json()

    assert message == {"endpoint_id": "n0", "available": True, "cpu_percent": 1.0}


def test_ws_buckets_route_is_absent_without_a_broadcaster():
    db = mongomock.MongoClient()["test"]
    collections = ReadCollections(endpoints=db["endpoints"], functions=db["functions"], consensus=db["consensus"])
    app = create_app(collections=collections, activity_repository=MongoActivityRepository(db["unified_activity"]))
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    assert not any(getattr(route, "path", None) == "/ws/buckets" for route in app.routes)
