from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from axo_vem.domain.workspace.value_objects import ResourceCapacity


@dataclass
class Function:
    """Entity for one registered function version, child of an Endpoint
    aggregate. Shape mirrors FunctionRegistered/Deployed/Activated/
    Deactivated/IdleRecycled/Deleted (see axo_shared/events/models.py) --
    no single event carries the full shape, so this is new modeling (no
    prior class existed; the read side historically returned raw Mongo
    dicts assembled incrementally by projector/upserts.py's upsert_function).

    capacity is never populated by any current event producer -- see
    Endpoint.check_capacity_invariant()'s docstring.

    endpoint_id is the set of nodes currently known to hold this version --
    a function isn't pinned to the one node that originally processed
    FunctionRegistered: axo_endpoint's cluster consensus replicates the
    record to every other node in that mesh, and each of those followers
    now announces itself too (FUNCTION_REPLICATED_EVENT ->
    ExternalEventForwardingBridge.on_function_event, same as the origin's
    own FunctionRegistered), so this accumulates via $addToSet in
    FunctionRepository.apply_event_data rather than being overwritten.
    Kept as a list under the same field name (not renamed to endpoint_ids)
    by design. This is the field DeleteFunctionUseCase/UpdateFunctionUseCase
    iterate through (trying each until one is reachable) instead of a
    caller-picked endpoint, and what PurgeEndpointUseCase removes single
    entries from via detach_endpoint_from_event() when other endpoints
    still hold the function. virtual_environment_id mirrors the most
    recently reporting node's own VE assignment at the time of its most
    recent lifecycle event -- coincides with the VE used to compute
    function_id at register time, but isn't guaranteed immutable if a
    node's VE assignment later changes and a subsequent event re-$sets it."""

    function_id: str
    version: int
    runtime_spec: Optional[Dict[str, Any]] = None
    owner_user_id: Optional[str] = None
    capacity: Optional[ResourceCapacity] = None
    deleted_at: Optional[str] = None
    endpoint_id: List[str] = field(default_factory=list)
    virtual_environment_id: Optional[str] = None
    # Derived by the projector from which of FunctionDeployed/DeployFailed/
    # Activated/Deactivated/Stopped/Crashed landed most recently -- no event
    # itself carries a status field, mirrors Endpoint's own status derivation
    # (see application/projector/compute_handler.py). "running" or "stopped";
    # None until the first such event lands.
    container_status: Optional[str] = None
