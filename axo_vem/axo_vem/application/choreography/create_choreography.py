from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from axo_vem.domain.choreography.choreography import stream_name
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher


class CreateChoreographyUseCase:
    def __init__(self, event_publisher: EventPublisher) -> None:
        self._event_publisher = event_publisher

    def execute(self, *, name: str, owner_user_id: str, graph: models.ChoreographyGraph) -> Dict[str, Any]:
        event = models.ChoreographyCreated(
            choreography_id=str(uuid.uuid4()),
            name=name,
            owner_user_id=owner_user_id,
            graph=graph,
        )
        data = event.model_dump(mode="json")
        self._event_publisher.append_to_stream(
            stream_name(event.choreography_id), models.CHOREOGRAPHY_CREATED, data,
        )
        return data
