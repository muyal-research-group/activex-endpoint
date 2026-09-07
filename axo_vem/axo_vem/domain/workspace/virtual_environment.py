from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from axo_vem.domain.errors import NotOwnerError
from axo_vem.domain.workspace.errors import WorkspaceCapacityExceededError
from axo_vem.domain.workspace.value_objects import ResourceCapacity


def stream_name(virtual_environment_id: str) -> str:
    return f"virtual-environments-{virtual_environment_id}"


@dataclass
class VirtualEnvironment:
    """Aggregate root for a logical multi-tenant workspace. Shape mirrors
    VirtualEnvironmentCreated/Updated (see axo_shared/events/models.py) --
    capacity is that event's resource_quota, renamed to the domain vocabulary.

    deployed_endpoint_capacities is never populated by any event producer
    today (no event reports an endpoint's capacity or its VE assignment
    together with a capacity figure) -- it defaults empty, which makes
    check_capacity_invariant() trivially satisfied until a future producer
    exists to populate it.
    """

    virtual_environment_id: str
    name: str
    owner_user_id: str
    capacity: ResourceCapacity
    deployed_endpoint_capacities: List[ResourceCapacity] = field(default_factory=list)
    # Which of this VE's assigned endpoints is currently the mesh-wide Bully
    # leader, if any (None if the leader isn't one of this VE's endpoints, or
    # no election has happened yet). Set directly by the projector's
    # compute_handler when a LeaderElected/ConsensusViewChanged resolves to
    # an endpoint belonging to this VE -- not part of any VE domain event
    # payload itself (see VirtualEnvironmentLeaderChanged's audit-only role).
    leader_endpoint_id: Optional[str] = None

    def assert_owner(self, user_id: str) -> None:
        if self.owner_user_id != user_id:
            raise NotOwnerError(f"{user_id} is not the owner of virtual environment {self.virtual_environment_id}")

    def check_capacity_invariant(self) -> None:
        """The workspace rule: sum of deployed endpoint capacities must not
        exceed the virtual environment's own declared capacity."""
        total = ResourceCapacity(cpu=0.0, ram=0, disk=0)
        for capacity in self.deployed_endpoint_capacities:
            total = total + capacity
        if not total.fits_within(self.capacity):
            raise WorkspaceCapacityExceededError(
                f"deployed endpoint capacities {total} exceed virtual environment "
                f"{self.virtual_environment_id}'s capacity {self.capacity}"
            )

    def to_dict(self) -> dict:
        """Reproduces the exact response body VE routes return today --
        virtual_environment_id/name/owner_user_id/resource_quota, same field
        names as projector/upserts.py's upsert_virtual_environment writes."""
        return {
            "virtual_environment_id": self.virtual_environment_id,
            "name": self.name,
            "owner_user_id": self.owner_user_id,
            "resource_quota": {"cpu": self.capacity.cpu, "ram": self.capacity.ram, "disk": self.capacity.disk},
            "leader_endpoint_id": self.leader_endpoint_id,
        }


def capacity_from_quota_dict(quota: dict) -> ResourceCapacity:
    return ResourceCapacity(cpu=quota["cpu"], ram=quota["ram"], disk=quota["disk"])
