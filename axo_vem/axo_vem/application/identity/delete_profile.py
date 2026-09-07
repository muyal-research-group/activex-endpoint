from __future__ import annotations

from axo_vem.domain.errors import NotFoundError
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.domain.identity.repository import UserProfileRepository
from axo_vem.domain.identity.user_profile import stream_name


class DeleteProfileUseCase:
    """Replaces the body of the former DELETE /profile route handler
    (api/routes/user_profile.py)."""

    def __init__(self, repository: UserProfileRepository, event_publisher: EventPublisher) -> None:
        self._repository = repository
        self._event_publisher = event_publisher

    def execute(self, *, user_id: str) -> None:
        if self._repository.get_by_user_id(user_id) is None:
            raise NotFoundError("profile not found")

        event = models.UserProfileDeleted(user_id=user_id)
        self._event_publisher.append_to_stream(
            stream_name(user_id), models.USER_PROFILE_DELETED, event.model_dump(mode="json"),
        )
