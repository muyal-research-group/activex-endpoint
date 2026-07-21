from fastapi.testclient import TestClient

from axo_shared.activity.repository import InMemoryRepository

from axo_vem.infrastructure.transport.api.app import create_app


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_events_route_is_absent_when_no_kurrent_reader_supplied(collections):
    app = create_app(collections=collections, activity_repository=InMemoryRepository(), kurrent_reader=None)
    client = TestClient(app)
    response = client.get("/events/endpoints/n0")
    assert response.status_code == 404
    # FastAPI's own "route not found" (no matching path), not our route's
    # "stream not found" -- confirmed by the default detail text differing.
    assert response.json()["detail"] == "Not Found"
