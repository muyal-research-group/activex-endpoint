from __future__ import annotations

from typing import Any, Dict

from axo_vem.domain.errors import NotFoundError
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository
from axo_vem.domain.workspace.virtual_environment import stream_name


class UpdateVirtualEnvironmentUseCase:
    """Replaces the body of the former PUT /virtual-environments/{id} route
    handler (api/routes/virtual_environments.py). Ownership is enforced via
    VirtualEnvironment.assert_owner() rather than the old inline
    `if doc["owner_user_id"] != current_user.key` check."""

    def __init__(self, repository: VirtualEnvironmentRepository, event_publisher: EventPublisher) -> None:
        self._repository = repository
        self._event_publisher = event_publisher

    def execute(
        self, *, virtual_environment_id: str, current_user_id: str, name: str, cpu: float, ram: int, disk: int,
    ) -> Dict[str, Any]:
        virtual_environment = self._repository.get(virtual_environment_id)
        if virtual_environment is None:
            raise NotFoundError("virtual environment not found")
        virtual_environment.assert_owner(current_user_id)

        event = models.VirtualEnvironmentUpdated(
            virtual_environment_id=virtual_environment_id,
            name=name,
            resource_quota=models.ResourceQuota(cpu=cpu, ram=ram, disk=disk),
        )
        data = event.model_dump(mode="json")
        self._event_publisher.append_to_stream(stream_name(virtual_environment_id), models.VIRTUAL_ENV_UPDATED, data)
        return data
