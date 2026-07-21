import json
from dataclasses import dataclass


@dataclass
class _FakeRecord:
    type: str
    data: bytes
    commit_position: int


def test_get_raw_events_returns_stream_records(client, fake_kurrent_reader):
    fake_kurrent_reader._streams["endpoints-n0"] = [
        _FakeRecord(type="EndpointRegistered", data=json.dumps({"endpoint_id": "n0"}).encode(), commit_position=1),
    ]

    response = client.get("/events/endpoints/n0")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["type"] == "EndpointRegistered"
    assert body[0]["data"] == {"endpoint_id": "n0"}
    assert body[0]["commit_position"] == 1


def test_get_raw_events_returns_404_for_unknown_stream(client):
    response = client.get("/events/endpoints/missing")
    assert response.status_code == 404


def test_get_raw_events_returns_404_for_empty_stream(client, fake_kurrent_reader):
    fake_kurrent_reader._streams["endpoints-empty"] = []
    response = client.get("/events/endpoints/empty")
    assert response.status_code == 404
