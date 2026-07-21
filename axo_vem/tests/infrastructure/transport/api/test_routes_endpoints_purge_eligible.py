from datetime import datetime, timedelta, timezone

from .conftest import FAKE_USER


def _iso(dt):
    return dt.isoformat()


def test_stopped_endpoint_is_purge_eligible_immediately(client, collections):
    collections.endpoints.insert_one({"_id": "n0", "endpoint_id": "n0", "status": "stopped"})

    response = client.get("/endpoints/n0")
    assert response.status_code == 200
    body = response.json()
    assert body["purge_eligible"] is True
    assert body["unreachable_since"] is None


def test_recently_unreachable_endpoint_is_not_yet_purge_eligible(client, collections):
    """No user_profile_repository override in play here -- falls back to
    the create_app-configured default (60 minutes in tests)."""
    just_now = datetime.now(timezone.utc)
    collections.endpoints.insert_one({
        "_id": "n0", "endpoint_id": "n0", "status": "unreachable", "created_at": _iso(just_now),
    })

    response = client.get("/endpoints/n0")
    assert response.status_code == 200
    body = response.json()
    assert body["purge_eligible"] is False
    assert body["unreachable_since"] == _iso(just_now)


def test_long_unreachable_endpoint_is_purge_eligible(client, collections):
    long_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    collections.endpoints.insert_one({
        "_id": "n0", "endpoint_id": "n0", "status": "unreachable", "created_at": _iso(long_ago),
    })

    response = client.get("/endpoints/n0")
    assert response.status_code == 200
    assert response.json()["purge_eligible"] is True


def test_running_endpoint_is_never_purge_eligible(client, collections):
    collections.endpoints.insert_one({"_id": "n0", "endpoint_id": "n0", "status": "running"})

    response = client.get("/endpoints/n0")
    assert response.status_code == 200
    body = response.json()
    assert body["purge_eligible"] is False
    assert body["unreachable_since"] is None


def test_purge_eligibility_honors_the_callers_own_profile_preference(client, collections, db):
    """A caller with a shorter endpoint_purge_eligible_after_minutes
    preference sees purge_eligible flip to True sooner than the system
    default would allow -- resolved per FAKE_USER.key, mirroring
    history.py's _since_for."""
    db["user_profiles"].insert_one({
        "_id": FAKE_USER.key, "user_id": FAKE_USER.key, "profile_photo": "",
        "preferences": {
            "color": None, "view_mode": "list", "language": "en",
            "activity_window_minutes": 60, "endpoint_purge_eligible_after_minutes": 5,
        },
    })
    ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    collections.endpoints.insert_one({
        "_id": "n0", "endpoint_id": "n0", "status": "unreachable", "created_at": _iso(ten_minutes_ago),
    })

    response = client.get("/endpoints/n0")
    assert response.status_code == 200
    assert response.json()["purge_eligible"] is True
