from datetime import datetime, timedelta, timezone

from xolo.client.models import UserDTO

from axo_shared.events import models

from .conftest import FAKE_USER, _fake_current_user

OTHER_USER = UserDTO(
    key="user-2", username="bob", first_name="Bob", last_name="B",
    email="bob@example.com", profile_photo="",
)


def _seed_function_registered(kurrent_appender, function_id="add", endpoint_id="n0"):
    event = models.FunctionRegistered(endpoint_id=endpoint_id, function_id=function_id, version=1)
    kurrent_appender.append_to_stream(
        f"functions-{function_id}", models.FUNCTION_REGISTERED, event.model_dump(mode="json"),
    )
    return event


def _seed_endpoint_started(kurrent_appender, endpoint_id="n0"):
    event = models.EndpointStarted(
        endpoint_id=endpoint_id, router_bind="tcp://0.0.0.0:5555", pub_bind="tcp://0.0.0.0:5556",
    )
    kurrent_appender.append_to_stream(f"endpoints-{endpoint_id}", models.ENDPOINT_STARTED, event.model_dump(mode="json"))
    return event


def test_history_with_no_params_returns_full_timeline(client, kurrent_appender):
    _seed_function_registered(kurrent_appender, function_id="add")
    _seed_endpoint_started(kurrent_appender, endpoint_id="n0")

    response = client.get("/history")
    assert response.status_code == 200
    event_types = {e["event_type"] for e in response.json()}
    assert event_types == {models.FUNCTION_REGISTERED, models.ENDPOINT_STARTED}


def test_history_filters_by_function_id(client, kurrent_appender):
    _seed_function_registered(kurrent_appender, function_id="add")
    _seed_function_registered(kurrent_appender, function_id="sub")

    response = client.get("/history", params={"function_id": "add"})
    assert response.status_code == 200
    docs = response.json()
    assert len(docs) == 1
    assert docs[0]["meta"]["function_id"] == "add"


def test_function_history_route_scopes_by_path_param(client, kurrent_appender):
    _seed_function_registered(kurrent_appender, function_id="add")
    _seed_function_registered(kurrent_appender, function_id="sub")

    response = client.get("/functions/add/history")
    assert response.status_code == 200
    docs = response.json()
    assert len(docs) == 1
    assert docs[0]["meta"]["function_id"] == "add"


def test_endpoint_history_route_scopes_by_path_param(client, kurrent_appender):
    _seed_endpoint_started(kurrent_appender, endpoint_id="n0")
    _seed_endpoint_started(kurrent_appender, endpoint_id="n1")

    response = client.get("/endpoints/n0/history")
    assert response.status_code == 200
    docs = response.json()
    assert len(docs) == 1
    assert docs[0]["endpoint_id"] == "n0"


def test_active_object_history_route_returns_empty_no_source_yet(client, kurrent_appender):
    """No event in the taxonomy carries active_object_id today -- this
    documents the expected always-empty result until Active Object
    mesh-side instrumentation exists, rather than leaving it untested."""
    _seed_function_registered(kurrent_appender, function_id="add")

    response = client.get("/active-objects/anything/history")
    assert response.status_code == 200
    assert response.json() == []


def test_history_default_window_excludes_events_older_than_an_hour(client, kurrent_appender):
    old_event = models.FunctionRegistered(
        endpoint_id="n0", function_id="old-fn", version=1,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    kurrent_appender.append_to_stream(
        "functions-old-fn", models.FUNCTION_REGISTERED, old_event.model_dump(mode="json"),
    )
    _seed_function_registered(kurrent_appender, function_id="recent-fn")

    response = client.get("/history")
    function_ids = {e["meta"]["function_id"] for e in response.json()}
    assert function_ids == {"recent-fn"}


def test_history_widening_activity_window_minutes_preference_includes_older_events(client, kurrent_appender):
    old_event = models.FunctionRegistered(
        endpoint_id="n0", function_id="old-fn", version=1,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    kurrent_appender.append_to_stream(
        "functions-old-fn", models.FUNCTION_REGISTERED, old_event.model_dump(mode="json"),
    )

    # Default 60-minute window excludes it.
    assert client.get("/history").json() == []

    # POST /profile itself lands its own UserProfileCreated row in
    # unified_activity, so filter down to just the FunctionRegistered rows
    # this test actually cares about.
    client.post("/profile", json={
        "profile_photo": "", "color": None, "view_mode": "list", "language": "en",
        "activity_window_minutes": 300,
    })

    response = client.get("/history")
    function_ids = {
        e["meta"]["function_id"] for e in response.json() if e["event_type"] == models.FUNCTION_REGISTERED
    }
    assert function_ids == {"old-fn"}


def test_user_profile_history_requires_self(client):
    response = client.get(f"/user-profiles/{FAKE_USER.key}/history")
    assert response.status_code == 200


def test_user_profile_history_rejects_other_users(client):
    client.app.dependency_overrides[_fake_current_user] = lambda: OTHER_USER
    try:
        response = client.get(f"/user-profiles/{FAKE_USER.key}/history")
        assert response.status_code == 403
    finally:
        del client.app.dependency_overrides[_fake_current_user]


def test_virtual_environment_history_requires_ownership(client):
    create_response = client.post(
        "/virtual-environments", json={"name": "dev-env", "cpu": 1.0, "ram": 512, "disk": 1024},
    )
    ve_id = create_response.json()["virtual_environment_id"]

    response = client.get(f"/virtual-environments/{ve_id}/history")
    assert response.status_code == 200


def test_virtual_environment_history_rejects_non_owner(client):
    create_response = client.post(
        "/virtual-environments", json={"name": "dev-env", "cpu": 1.0, "ram": 512, "disk": 1024},
    )
    ve_id = create_response.json()["virtual_environment_id"]

    client.app.dependency_overrides[_fake_current_user] = lambda: OTHER_USER
    try:
        response = client.get(f"/virtual-environments/{ve_id}/history")
        assert response.status_code == 403
    finally:
        del client.app.dependency_overrides[_fake_current_user]


def test_virtual_environment_history_unknown_id_returns_404(client):
    response = client.get("/virtual-environments/missing/history")
    assert response.status_code == 404
