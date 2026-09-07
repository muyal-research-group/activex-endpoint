from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from axo_vem.domain.errors import NotOwnerError
from axo_vem.domain.events.models import ChoreographyGraph


def stream_name(choreography_id: str) -> str:
    return f"choreographies-{choreography_id}"


@dataclass
class Choreography:
    """Aggregate root for one saved workflow graph. Shape mirrors
    ChoreographyCreated/Updated (see axo_shared/events/models.py) -- graph
    is that event's own ChoreographyGraph (nodes + edges), unchanged.

    Unlike VirtualEnvironment, a Choreography has no immutable-after-creation
    fields besides owner_user_id -- name and graph are both freely rewritable
    via update, gated only by "no active run" (enforced by
    UpdateChoreographyUseCase via ChoreographyRunRepository, not here)."""

    choreography_id: str
    name: str
    owner_user_id: str
    graph: ChoreographyGraph
    created_at: str
    updated_at: str

    def assert_owner(self, user_id: str) -> None:
        if self.owner_user_id != user_id:
            raise NotOwnerError(f"{user_id} is not the owner of choreography {self.choreography_id}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "choreography_id": self.choreography_id,
            "name": self.name,
            "owner_user_id": self.owner_user_id,
            "graph": self.graph.model_dump(mode="json"),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
