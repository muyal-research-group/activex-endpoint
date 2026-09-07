from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class ActiveObjectRecord:
    """Shape only -- no repository, projector wiring, Kurrent event, or HTTP
    route exists for this yet (see plan phase 7). Deferred because no
    mesh-side event source for Active Object lifecycle exists today; wiring
    this up means adding that instrumentation first, which is out of scope
    for this round.

    Modeled like Function: an endpoint may execute the same ActiveObject as
    any other endpoint, so the relationship is soft (seen_on_endpoints, a
    denormalized list) rather than a strict foreign key to one owning
    endpoint.
    """

    id: str
    owner_user_id: Optional[str]
    class_name: str
    state: str
    created_at: float
    seen_on_endpoints: List[str] = field(default_factory=list)
