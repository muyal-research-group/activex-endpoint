from __future__ import annotations

from pymongo.collection import Collection

from axo_vem.domain.errors import ConflictError, NotFoundError
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository
from axo_vem.domain.workspace.virtual_environment import stream_name


class DeleteVirtualEnvironmentUseCase:
    """Replaces the body of the former DELETE /virtual-environments/{id}
    route handler (api/routes/virtual_environments.py). Does not call
    repository.soft_delete() synchronously -- same as today, the actual
    soft-delete is applied asynchronously once the projector consumes the
    VirtualEnvironmentDeleted event (see application/projector/workspace_handler.py)."""

    def __init__(
        self,
        repository: VirtualEnvironmentRepository,
        event_publisher: EventPublisher,
        endpoints: Collection,
    ) -> None:
        self._repository = repository
        self._event_publisher = event_publisher
        self._endpoints = endpoints

    def execute(self, *, virtual_environment_id: str, current_user_id: str) -> None:
        virtual_environment = self._repository.get(virtual_environment_id)
        if virtual_environment is None:
            raise NotFoundError("virtual environment not found")
        virtual_environment.assert_owner(current_user_id)

        if self._endpoints.count_documents({"virtual_environment_id": virtual_environment_id}) > 0:
            raise ConflictError("virtual environment has endpoints assigned")

        event = models.VirtualEnvironmentDeleted(virtual_environment_id=virtual_environment_id)
        self._event_publisher.append_to_stream(
            stream_name(virtual_environment_id), models.VIRTUAL_ENV_DELETED, event.model_dump(mode="json"),
        )
