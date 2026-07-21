import mongomock

from axo_vem.domain.events.models import Preferences
from axo_vem.domain.identity.user_profile import UserProfile
from axo_vem.infrastructure.database.mongo.user_profile_repository import MongoUserProfileRepository


def _repository():
    db = mongomock.MongoClient()["test"]
    return MongoUserProfileRepository(db["user_profiles"])


def test_get_by_user_id_returns_none_when_missing():
    repository = _repository()
    assert repository.get_by_user_id("missing") is None


def test_save_then_get_round_trips():
    repository = _repository()
    repository.save(UserProfile("u1", "p.png", Preferences(color="#fff", view_mode="grid", language="en")))

    profile = repository.get_by_user_id("u1")
    assert profile.profile_photo == "p.png"
    assert profile.preferences.view_mode == "grid"


def test_save_is_idempotent_upsert():
    repository = _repository()
    repository.save(UserProfile("u1", "a.png", Preferences()))
    repository.save(UserProfile("u1", "b.png", Preferences()))

    profile = repository.get_by_user_id("u1")
    assert profile.profile_photo == "b.png"


def test_delete_removes_the_profile():
    repository = _repository()
    repository.save(UserProfile("u1", "p.png", Preferences()))
    repository.delete("u1")
    assert repository.get_by_user_id("u1") is None
