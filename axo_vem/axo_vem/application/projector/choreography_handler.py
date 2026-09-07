from __future__ import annotations

from typing import Any, Dict

from axo_vem.domain.choreography.choreography import Choreography
from axo_vem.domain.choreography.repository import ChoreographyRepository
from axo_vem.domain.events import models
from axo_vem.domain.events.models import ChoreographyGraph

CHOREOGRAPHY_EVENT_TYPES = frozenset({
    models.CHOREOGRAPHY_CREATED, models.CHOREOGRAPHY_UPDATED, models.CHOREOGRAPHY_DELETED,
})


def apply(repository: ChoreographyRepository, event_type: str, data: Dict[str, Any]) -> None:
    """ChoreographyCreated carries the full aggregate shape (including
    owner_user_id); ChoreographyUpdated omits owner_user_id and the original
    created_at (both immutable after creation), so applying it first fetches
    the existing aggregate to preserve them -- same fetch-then-merge pattern
    workspace_handler.py uses for VIRTUAL_ENV_UPDATED."""
    if event_type == models.CHOREOGRAPHY_CREATED:
        choreography = Choreography(
            choreography_id=data["choreography_id"],
            name=data["name"],
            owner_user_id=data["owner_user_id"],
            graph=ChoreographyGraph.model_validate(data["graph"]),
            created_at=data["created_at"],
            updated_at=data["created_at"],
        )
        repository.save(choreography)
    elif event_type == models.CHOREOGRAPHY_UPDATED:
        existing = repository.get(data["choreography_id"])
        owner_user_id = existing.owner_user_id if existing is not None else None
        created_at = existing.created_at if existing is not None else data["created_at"]
        choreography = Choreography(
            choreography_id=data["choreography_id"],
            name=data["name"],
            owner_user_id=owner_user_id,
            graph=ChoreographyGraph.model_validate(data["graph"]),
            created_at=created_at,
            updated_at=data["created_at"],
        )
        repository.save(choreography)
    elif event_type == models.CHOREOGRAPHY_DELETED:
        repository.soft_delete(data["choreography_id"], data["created_at"])
