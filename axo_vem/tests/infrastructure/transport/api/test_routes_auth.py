from option import Err

from xolo.client.errors import UnauthorizedError, ValidationError

_SIGNUP_BODY = {
    "username": "carol",
    "first_name": "Carol",
    "last_name": "C",
    "email": "carol@example.com",
    "password": "hunter2",
    "scope": "USERS",
}


def test_signup_creates_local_profile(client, fake_xolo_client):
    response = client.post("/signup", json=_SIGNUP_BODY)

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == fake_xolo_client.signup_result.unwrap().key
    assert fake_xolo_client.signup_calls[0]["username"] == "carol"

    get_response = client.get("/profile")
    assert get_response.status_code == 200


def test_signup_propagates_xolo_failure(client, fake_xolo_client):
    fake_xolo_client.signup_result = Err(ValidationError("username taken"))

    response = client.post("/signup", json=_SIGNUP_BODY)

    assert response.status_code == 422
    assert response.json()["detail"] == "username taken"


def test_login_returns_session_tokens(client, fake_xolo_client):
    response = client.post("/login", json={"username": "alice", "password": "hunter2"})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "tok123"
    assert body["temporal_secret"] == "sec456"
    assert fake_xolo_client.auth_calls[0]["username"] == "alice"


def test_login_propagates_xolo_failure(client, fake_xolo_client):
    fake_xolo_client.auth_result = Err(UnauthorizedError("bad credentials"))

    response = client.post("/login", json={"username": "alice", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"] == "bad credentials"
