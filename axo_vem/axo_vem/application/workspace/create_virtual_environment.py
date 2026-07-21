from __future__ import annotations

import uuid
from typing import Any, Dict

from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.domain.workspace.virtual_environment import stream_name


class CreateVirtualEnvironmentUseCase:
    """Replaces the body of the former POST /virtual-environments route
    handler (api/routes/virtual_environments.py)."""

    def __init__(self, event_publisher: EventPublisher) -> None:
        self._event_publisher = event_publisher

    def execute(self, *, name: str, owner_user_id: str, cpu: float, ram: int, disk: int) -> Dict[str, Any]:
        event = models.VirtualEnvironmentCreated(
            virtual_environment_id=str(uuid.uuid4()),
            name=name,
            owner_user_id=owner_user_id,
            resource_quota=models.ResourceQuota(cpu=cpu, ram=ram, disk=disk),
        )
        data = event.model_dump(mode="json")
        self._event_publisher.append_to_stream(
            stream_name(event.virtual_environment_id), models.VIRTUAL_ENV_CREATED, data,
        )
        return data
