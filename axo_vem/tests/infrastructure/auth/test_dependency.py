from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from option import Err, Ok
from xolo.client.errors import UnauthorizedError
from xolo.client.models import UserDTO

from axo_vem.infrastructure.auth.dependency import build_current_user_dependency, build_identity_dependency


class _FakeXoloClient:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def get_current_user(self, token, temporal_secret):
        self.calls.append((token, temporal_secret))
        return self._result


class _FakeUserProfileRepository:
    def __init__(self, profiles=None):
        self._profiles = profiles or {}

    def get_by_user_id(self, user_id):
        return self._profiles.get(user_id)


def _build_identity_app(xolo_client):
    dependency = build_identity_dependency(xolo_client)
    app = FastAPI()

    @app.get("/whoami")
    def whoami(current_user: UserDTO = Depends(dependency)):
        return {"username": current_user.username}

    return TestClient(app)


def _build_current_user_app(xolo_client, repository):
    dependency = build_current_user_dependency(xolo_client, repository)
    app = FastAPI()

    @app.get("/whoami")
    def whoami(current_user: UserDTO = Depends(dependency)):
        return {"username": current_user.username}

    return TestClient(app)


USER = UserDTO(key="u1", username="alice", first_name="A", last_name="B", email="a@b.com", profile_photo="")


def test_valid_credentials_return_user():
    xolo_client = _FakeXoloClient(Ok(USER))
    client = _build_identity_app(xolo_client)

    response = client.get(
        "/whoami", headers={"Authorization": "Bearer tok123", "Temporal-Secret-Key": "sec456"},
    )

    assert response.status_code == 200
    assert response.json() == {"username": "alice"}
    assert xolo_client.calls == [("tok123", "sec456")]


def test_bearer_alone_is_accepted_with_blank_temporal_secret():
    xolo_client = _FakeXoloClient(Ok(USER))
    client = _build_identity_app(xolo_client)

    response = client.get("/whoami", headers={"Authorization": "Bearer tok123"})

    assert response.status_code == 200
    assert xolo_client.calls == [("tok123", "")]


def test_xolo_error_translates_to_http_exception():
    xolo_client = _FakeXoloClient(Err(UnauthorizedError("bad token")))
    client = _build_identity_app(xolo_client)

    response = client.get(
        "/whoami", headers={"Authorization": "Bearer bad", "Temporal-Secret-Key": "sec"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "bad token"


def test_missing_bearer_returns_401():
    xolo_client = _FakeXoloClient(Ok(USER))
    client = _build_identity_app(xolo_client)

    response = client.get("/whoami", headers={"Temporal-Secret-Key": "sec"})

    assert response.status_code == 401
    assert xolo_client.calls == []


def test_current_user_dependency_returns_user_when_profile_exists():
    xolo_client = _FakeXoloClient(Ok(USER))
    repository = _FakeUserProfileRepository({"u1": {"_id": "u1"}})
    client = _build_current_user_app(xolo_client, repository)

    response = client.get(
        "/whoami", headers={"Authorization": "Bearer tok123", "Temporal-Secret-Key": "sec456"},
    )

    assert response.status_code == 200
    assert response.json() == {"username": "alice"}


def test_current_user_dependency_returns_404_when_profile_missing():
    xolo_client = _FakeXoloClient(Ok(USER))
    repository = _FakeUserProfileRepository({})
    client = _build_current_user_app(xolo_client, repository)

    response = client.get(
        "/whoami", headers={"Authorization": "Bearer tok123", "Temporal-Secret-Key": "sec456"},
    )

    assert response.status_code == 404


def test_current_user_dependency_returns_401_before_profile_lookup_on_bad_credentials():
    xolo_client = _FakeXoloClient(Err(UnauthorizedError("bad token")))
    repository = _FakeUserProfileRepository({"u1": {"_id": "u1"}})
    client = _build_current_user_app(xolo_client, repository)

    response = client.get(
        "/whoami", headers={"Authorization": "Bearer bad", "Temporal-Secret-Key": "sec"},
    )

    assert response.status_code == 401
