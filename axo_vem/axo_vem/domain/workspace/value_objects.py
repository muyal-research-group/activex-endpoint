from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceCapacity:
    """A declared or consumed amount of cpu/ram/disk. Shape mirrors
    axo_shared.events.models.ResourceQuota exactly (same three fields) --
    this is the canonical capacity value object, reused by domain/compute/
    for Endpoint/Function/ActiveObject capacities rather than redefining a
    second copy there.

    Not currently populated by any event producer for Endpoint/Function/
    ActiveObject (see domain/compute/endpoint.py) -- exists so the
    invariant-checking methods below are correct and unit-testable today,
    ready for a future wire-protocol change (out of scope, a separate
    axo_endpoint-side concern) to actually feed real capacity data through.
    """

    cpu: float
    ram: int
    disk: int

    def __add__(self, other: "ResourceCapacity") -> "ResourceCapacity":
        return ResourceCapacity(
            cpu=self.cpu + other.cpu,
            ram=self.ram + other.ram,
            disk=self.disk + other.disk,
        )

    def fits_within(self, capacity: "ResourceCapacity") -> bool:
        return self.cpu <= capacity.cpu and self.ram <= capacity.ram and self.disk <= capacity.disk
