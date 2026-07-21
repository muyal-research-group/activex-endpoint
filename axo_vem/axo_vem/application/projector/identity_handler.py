from __future__ import annotations

from typing import Any, Dict

from axo_vem.domain.events import models
from axo_vem.domain.events.models import Preferences
from axo_vem.domain.identity.repository import UserProfileRepository
from axo_vem.domain.identity.user_profile import UserProfile

UPSERT_EVENT_TYPES = frozenset({models.USER_PROFILE_CREATED, models.USER_PROFILE_UPDATED})


def apply(repository: UserProfileRepository, event_type: str, data: Dict[str, Any]) -> None:
    """UserProfileCreated/Updated both carry the full profile shape (unlike
    VirtualEnvironmentUpdated, which omits owner_user_id -- see
    workspace_handler.py), so both are plain replace-and-save. Replaces
    projector/upserts.py's former upsert_user_profile/delete_user_profile."""
    if event_type in UPSERT_EVENT_TYPES:
        preferences = data["preferences"]
        profile = UserProfile(
            user_id=data["user_id"],
            profile_photo=data["profile_photo"],
            preferences=Preferences(
                color=preferences.get("color"),
                view_mode=preferences.get("view_mode", "list"),
                language=preferences.get("language", "en"),
                activity_window_minutes=preferences.get("activity_window_minutes", 60),
                endpoint_purge_eligible_after_minutes=preferences.get("endpoint_purge_eligible_after_minutes", 60),
            ),
        )
        repository.save(profile)
    elif event_type == models.USER_PROFILE_DELETED:
        repository.delete(data["user_id"])
