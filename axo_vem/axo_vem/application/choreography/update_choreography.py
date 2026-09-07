from __future__ import annotations

from typing import Any, Dict

from axo_vem.domain.choreography.repository import ChoreographyRepository
from axo_vem.domain.choreography.run_repository import ChoreographyRunRepository
from axo_vem.domain.choreography.choreography import stream_name
from axo_vem.domain.errors import ConflictError, NotFoundError
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher


class UpdateChoreographyUseCase:
    """A choreography with an active run is not editable -- it must be
    stopped first (see ChoreographyRunRepository.has_active_run). This is
    the one rule VirtualEnvironment's own UpdateUseCase has no equivalent
    of, since a VE has no concept of "currently running"."""

    def __init__(
        self,
        repository: ChoreographyRepository,
        run_repository: ChoreographyRunRepository,
        event_publisher: EventPublisher,
    ) -> None:
        self._repository = repository
        self._run_repository = run_repository
        self._event_publisher = event_publisher

    def execute(
        self, *, choreography_id: str, current_user_id: str, name: str, graph: models.ChoreographyGraph,
    ) -> Dict[str, Any]:
        choreography = self._repository.get(choreography_id)
        if choreography is None:
            raise NotFoundError("choreography not found")
        choreography.assert_owner(current_user_id)

        if self._run_repository.has_active_run(choreography_id):
            raise ConflictError("choreography has an active run -- stop it before updating")

        event = models.ChoreographyUpdated(choreography_id=choreography_id, name=name, graph=graph)
        data = event.model_dump(mode="json")
        self._event_publisher.append_to_stream(stream_name(choreography_id), models.CHOREOGRAPHY_UPDATED, data)
        return data
