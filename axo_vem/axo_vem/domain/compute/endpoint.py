from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from axo_vem.domain.compute.active_object import ActiveObject
from axo_vem.domain.compute.errors import NodeCapacityExceededError
from axo_vem.domain.compute.function import Function
from axo_vem.domain.workspace.value_objects import ResourceCapacity


@dataclass
class Endpoint:
    """Aggregate root for one physical/virtual compute node, containing
    child entities Function and ActiveObject. No single event carries this
    full shape today -- it's assembled incrementally from EndpointStarted/
    MetricsReported/Stopped/VirtualEnvironmentAssigned/Detached (see
    axo_shared/events/models.py), same as the raw-dict read model
    projector/upserts.py's upsert_endpoint has always produced. This is new
    domain modeling: no Endpoint class existed before this migration.

    capacity is never populated by any current event producer -- no event
    reports an endpoint's own resource capacity. check_capacity_invariant()
    is therefore correct-but-inert today (None on either side skips the
    check) until a future axo_endpoint-side wire change feeds real data
    through -- that producer change is out of scope for this project.

    last_seen_at is a repurposed read of the doc's `created_at` field, which
    gets $set-overwritten by every EndpointStarted/EndpointMetricsReported
    (periodic heartbeat)/EndpointStopped event's own created_at (see
    EventEnvelope, axo_shared/axo_shared/events/models.py) -- a de facto
    liveness/recency signal used by RegisterFunctionUseCase to pick the
    "healthiest" VE-assigned endpoint, not a true endpoint creation
    timestamp. ISO-8601 string, like every other event-sourced timestamp in
    this codebase -- sort lexicographically, don't parse to datetime.
    """

    endpoint_id: str
    router_bind: Optional[str] = None
    pub_bind: Optional[str] = None
    status: Optional[str] = None
    virtual_environment_id: Optional[str] = None
    capacity: Optional[ResourceCapacity] = None
    functions: List[Function] = field(default_factory=list)
    active_objects: List[ActiveObject] = field(default_factory=list)
    last_seen_at: Optional[str] = None

    def check_capacity_invariant(self) -> None:
        """The node rule: sum of function and active-object capacities must
        not exceed the host endpoint's own capacity. Any capacity being
        unknown (None) skips enforcement rather than raising, since no event
        today carries these fields."""
        if self.capacity is None:
            return

        total = ResourceCapacity(cpu=0.0, ram=0, disk=0)
        for child in (*self.functions, *self.active_objects):
            if child.capacity is None:
                return
            total = total + child.capacity
        if not total.fits_within(self.capacity):
            raise NodeCapacityExceededError(
                f"function/active-object capacities {total} exceed endpoint "
                f"{self.endpoint_id}'s capacity {self.capacity}"
            )
