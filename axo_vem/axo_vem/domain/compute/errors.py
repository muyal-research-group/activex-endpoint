from __future__ import annotations

from axo_vem.domain.errors import ConflictError


class NodeCapacityExceededError(ConflictError):
    """Raised by Endpoint.check_capacity_invariant() when the sum of a
    host endpoint's function and active-object capacities would exceed its
    own declared capacity. Maps to HTTP 409, same as any other ConflictError."""
