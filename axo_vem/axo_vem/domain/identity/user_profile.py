from __future__ import annotations

from dataclasses import dataclass

from axo_vem.domain.events.models import Preferences


def stream_name(user_id: str) -> str:
    return f"user-profiles-{user_id}"


@dataclass
class UserProfile:
    """Aggregate root for a local user profile -- the projected, current
    state derived from UserProfileCreated/Updated events. Shape mirrors
    those two events exactly (see axo_shared/events/models.py) since that's
    the only producer."""

    user_id: str
    profile_photo: str
    preferences: Preferences

    def to_dict(self) -> dict:
        """Reproduces the exact response body GET /profile returns today
        (strip_id(doc) over the Mongo document projector/upserts.py's
        upsert_user_profile writes -- user_id/profile_photo/preferences,
        same field names)."""
        return {
            "user_id": self.user_id,
            "profile_photo": self.profile_photo,
            "preferences": {
                "color": self.preferences.color,
                "view_mode": self.preferences.view_mode,
                "language": self.preferences.language,
                "activity_window_minutes": self.preferences.activity_window_minutes,
                "endpoint_purge_eligible_after_minutes": self.preferences.endpoint_purge_eligible_after_minutes,
            },
        }
