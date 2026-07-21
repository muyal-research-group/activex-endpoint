from __future__ import annotations

from typing import Optional

from pymongo.collection import Collection

from axo_vem.domain.events.models import Preferences
from axo_vem.domain.identity.repository import UserProfileRepository
from axo_vem.domain.identity.user_profile import UserProfile


def _doc_to_profile(doc: dict) -> UserProfile:
    preferences = doc.get("preferences") or {}
    return UserProfile(
        user_id=doc["user_id"],
        profile_photo=doc.get("profile_photo", ""),
        preferences=Preferences(
            color=preferences.get("color"),
            view_mode=preferences.get("view_mode", "list"),
            language=preferences.get("language", "en"),
            activity_window_minutes=preferences.get("activity_window_minutes", 60),
            endpoint_purge_eligible_after_minutes=preferences.get("endpoint_purge_eligible_after_minutes", 60),
        ),
    )


class MongoUserProfileRepository(UserProfileRepository):
    """Read/write access to the user_profiles collection -- a bespoke,
    single-purpose repository (not the generic Repository[T], whose
    list_by_function_id shape doesn't fit this aggregate), same rationale
    the old repository/user_profile.py documented. Writes are applied by
    the projector (application/projector/identity_handler.py) after a
    UserProfile* event lands in Kurrent; save()/delete() absorb
    projector/upserts.py's former upsert_user_profile/delete_user_profile.
    """

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get_by_user_id(self, user_id: str) -> Optional[UserProfile]:
        doc = self._collection.find_one({"_id": user_id})
        if doc is None:
            return None
        return _doc_to_profile(doc)

    def save(self, profile: UserProfile) -> None:
        data = {
            "user_id": profile.user_id,
            "profile_photo": profile.profile_photo,
            "preferences": {
                "color": profile.preferences.color,
                "view_mode": profile.preferences.view_mode,
                "language": profile.preferences.language,
                "activity_window_minutes": profile.preferences.activity_window_minutes,
                "endpoint_purge_eligible_after_minutes": profile.preferences.endpoint_purge_eligible_after_minutes,
            },
        }
        self._collection.update_one({"_id": profile.user_id}, {"$set": data}, upsert=True)

    def delete(self, user_id: str) -> None:
        """A user profile has no other party relying on its historical
        continuity (unlike VirtualEnvironment, which an Endpoint may
        reference), so this is a real delete, not a soft-delete marker."""
        self._collection.delete_one({"_id": user_id})
