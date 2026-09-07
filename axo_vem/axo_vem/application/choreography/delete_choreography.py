from __future__ import annotations

from axo_vem.domain.choreography.repository import ChoreographyRepository
from axo_vem.domain.choreography.run_repository import ChoreographyRunRepository
from axo_vem.domain.choreography.choreography import stream_name
from axo_vem.domain.errors import ConflictError, NotFoundError
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher


class DeleteChoreographyUseCase:
    def __init__(
        self,
        repository: ChoreographyRepository,
        run_repository: ChoreographyRunRepository,
        event_publisher: EventPublisher,
    ) -> None:
        self._repository = repository
        self._run_repository = run_repository
        self._event_publisher = event_publisher

    def execute(self, *, choreography_id: str, current_user_id: str) -> None:
        choreography = self._repository.get(choreography_id)
        if choreography is None:
            raise NotFoundError("choreography not found")
        choreography.assert_owner(current_user_id)

        if self._run_repository.has_active_run(choreography_id):
            raise ConflictError("choreography has an active run -- stop it before deleting")

        event = models.ChoreographyDeleted(choreography_id=choreography_id)
        self._event_publisher.append_to_stream(
            stream_name(choreography_id), models.CHOREOGRAPHY_DELETED, event.model_dump(mode="json"),
        )
