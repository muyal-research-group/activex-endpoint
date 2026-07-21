from __future__ import annotations

from typing import Any, Dict, Optional

from axo_vem.domain.errors import ConflictError
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.domain.identity.repository import UserProfileRepository
from axo_vem.domain.identity.user_profile import stream_name


class CreateProfileUseCase:
    """Replaces the body of the former POST /profile route handler
    (api/routes/user_profile.py) -- used for identities provisioned some
    other way than POST /signup (e.g. via XoloClient.create_user through
    the admin API)."""

    def __init__(self, repository: UserProfileRepository, event_publisher: EventPublisher) -> None:
        self._repository = repository
        self._event_publisher = event_publisher

    def execute(
        self, *, user_id: str, profile_photo: str, color: Optional[str], view_mode: str, language: str,
        activity_window_minutes: int = 60, endpoint_purge_eligible_after_minutes: int = 60,
    ) -> Dict[str, Any]:
        if self._repository.get_by_user_id(user_id) is not None:
            raise ConflictError("profile already exists")

        preferences = models.Preferences(
            color=color, view_mode=view_mode, language=language,
            activity_window_minutes=activity_window_minutes,
            endpoint_purge_eligible_after_minutes=endpoint_purge_eligible_after_minutes,
        )
        event = models.UserProfileCreated(user_id=user_id, profile_photo=profile_photo, preferences=preferences)
        data = event.model_dump(mode="json")
        self._event_publisher.append_to_stream(stream_name(user_id), models.USER_PROFILE_CREATED, data)
        return data
