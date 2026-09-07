def test_get_profile_returns_404_when_none_exists(client):
    response = client.get("/profile")
    assert response.status_code == 404


def test_create_get_update_delete_profile_round_trip(client):
    create_response = client.post("/profile", json={
        "profile_photo": "photo.png", "color": "#ff0000", "view_mode": "grid", "language": "es",
    })
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["user_id"] == "user-1"
    assert body["profile_photo"] == "photo.png"
    assert body["preferences"] == {
        "color": "#ff0000", "view_mode": "grid", "language": "es", "activity_window_minutes": 60,
        "endpoint_purge_eligible_after_minutes": 60,
    }

    get_response = client.get("/profile")
    assert get_response.status_code == 200
    assert get_response.json()["preferences"]["view_mode"] == "grid"

    update_response = client.put("/profile", json={
        "profile_photo": "photo2.png", "color": "#00ff00", "view_mode": "list", "language": "en",
    })
    assert update_response.status_code == 200
    assert update_response.json()["preferences"]["view_mode"] == "list"

    get_after_update = client.get("/profile")
    assert get_after_update.json()["profile_photo"] == "photo2.png"

    delete_response = client.delete("/profile")
    assert delete_response.status_code == 204

    get_after_delete = client.get("/profile")
    assert get_after_delete.status_code == 404


def test_activity_window_minutes_round_trips_through_create_and_update(client):
    create_response = client.post("/profile", json={
        "profile_photo": "", "color": None, "view_mode": "list", "language": "en",
        "activity_window_minutes": 15,
    })
    assert create_response.json()["preferences"]["activity_window_minutes"] == 15

    update_response = client.put("/profile", json={
        "profile_photo": "", "color": None, "view_mode": "list", "language": "en",
        "activity_window_minutes": 120,
    })
    assert update_response.json()["preferences"]["activity_window_minutes"] == 120

    get_response = client.get("/profile")
    assert get_response.json()["preferences"]["activity_window_minutes"] == 120


def test_endpoint_purge_eligible_after_minutes_round_trips_through_create_and_update(client):
    create_response = client.post("/profile", json={
        "profile_photo": "", "color": None, "view_mode": "list", "language": "en",
        "endpoint_purge_eligible_after_minutes": 5,
    })
    assert create_response.json()["preferences"]["endpoint_purge_eligible_after_minutes"] == 5

    update_response = client.put("/profile", json={
        "profile_photo": "", "color": None, "view_mode": "list", "language": "en",
        "endpoint_purge_eligible_after_minutes": 240,
    })
    assert update_response.json()["preferences"]["endpoint_purge_eligible_after_minutes"] == 240

    get_response = client.get("/profile")
    assert get_response.json()["preferences"]["endpoint_purge_eligible_after_minutes"] == 240


def test_create_profile_twice_returns_409(client):
    body = {"profile_photo": "", "color": None, "view_mode": "list", "language": "en"}
    first = client.post("/profile", json=body)
    assert first.status_code == 201

    second = client.post("/profile", json=body)
    assert second.status_code == 409


def test_update_profile_before_create_returns_404(client):
    response = client.put("/profile", json={
        "profile_photo": "x", "color": None, "view_mode": "list", "language": "en",
    })
    assert response.status_code == 404


def test_delete_profile_before_create_returns_404(client):
    response = client.delete("/profile")
    assert response.status_code == 404
