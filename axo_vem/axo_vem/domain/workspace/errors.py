from __future__ import annotations

from axo_vem.domain.errors import ConflictError


class WorkspaceCapacityExceededError(ConflictError):
    """Raised by VirtualEnvironment.check_capacity_invariant() when the sum
    of deployed endpoint capacities would exceed the workspace's declared
    capacity. Maps to HTTP 409, same as any other ConflictError."""
