from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from axo_vem.domain.workspace.value_objects import ResourceCapacity


@dataclass
class ActiveObject:
    """Entity for one active object instance, child of an Endpoint
    aggregate. Mirrors axo_shared.active_objects.models.ActiveObjectRecord's
    "shape only" precedent -- there is no repository wiring, projector
    branch, Kurrent event, or HTTP route for this yet in the wider service;
    this class exists purely so domain/compute/endpoint.py's node-capacity
    invariant has a typed child to sum over, ready for future wiring.

    An active object may run on more than one endpoint (soft relationship,
    denormalized seen_on_endpoints), same as the axo_shared stub it mirrors.
    """

    id: str
    class_name: str
    state: str
    owner_user_id: Optional[str] = None
    capacity: Optional[ResourceCapacity] = None
    seen_on_endpoints: List[str] = field(default_factory=list)
