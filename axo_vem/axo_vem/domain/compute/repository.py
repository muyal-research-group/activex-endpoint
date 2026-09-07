from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from axo_vem.domain.compute.endpoint import Endpoint
from axo_vem.domain.compute.function import Function


class EndpointRepository(ABC):
    """Write access for Endpoint aggregates, applied by the projector after
    a node-originated event arrives -- see
    application/projector/compute_handler.py. Read access for GET routes
    stays dict-based against the raw Mongo collection (decision 3 in the
    migration plan: Endpoint has no well-defined shape to safely reconstruct
    into an aggregate for HTTP responses), so get()/list_by_virtual_environment()
    stay narrow, aggregate-shaped reads for internal decision logic only --
    not a replacement for the raw-dict GET routes.

    apply_event_data() is the method the projector actually calls: a
    node-originated event's full decoded field set (including fields the
    narrow Endpoint aggregate doesn't model, e.g. metrics/uptime_ms) must
    reach the Mongo document unabridged, since that same document is what
    GET /endpoints returns verbatim (decision 3). Routing
    the projector's write path through save(endpoint) instead would
    silently drop those fields -- so apply_event_data(), not save(), is the
    real write contract; save()/get() exist for symmetry with the other
    aggregate repositories and future capacity-aware use cases.

    list_by_virtual_environment() is the first read method consumed outside
    the projector's own write path -- RegisterFunctionUseCase uses it to
    auto-pick a routing target for a function registered into a given VE,
    and LaunchEndpointNodeUseCase uses it (filtering to status == "running",
    reading pub_bind) to auto-derive a newly launched node's
    AXO_ENDPOINT_SUB_CONNECT from its VE's existing mesh peers.
    """

    @abstractmethod
    def save(self, endpoint: Endpoint) -> None: ...

    @abstractmethod
    def get(self, endpoint_id: str) -> Optional[Endpoint]: ...

    @abstractmethod
    def apply_event_data(self, endpoint_id: str, data: Dict[str, Any]) -> None: ...

    @abstractmethod
    def list_by_virtual_environment(self, virtual_environment_id: str) -> List[Endpoint]:
        """Endpoints currently assigned to this VE, ordered most-recently-seen
        first (see Endpoint.last_seen_at), tie-broken by endpoint_id ascending.
        Callers that just want a single routing target take index 0."""


class FunctionRepository(ABC):
    """Write access for Function entities, applied by the projector. Same
    read-side and apply_event_data() rationale as EndpointRepository above
    -- GET routes stay dict-based, and the projector's actual write path
    must preserve the full event field set.

    get() is consumed by DeleteFunctionUseCase/UpdateFunctionUseCase to
    resolve a function version's currently-known endpoint_id list, so
    routing tries each recorded endpoint rather than depending on a
    caller-picked endpoint or a re-derived function_id hash.

    list_by_endpoint_id() is consumed by PurgeEndpointUseCase to find every
    still-live (not yet soft-deleted) function version a purged endpoint
    was one of the holders of -- see detach_endpoint_from_event() below for
    what happens when other endpoints still hold it."""

    @abstractmethod
    def save(self, function: Function) -> None: ...

    @abstractmethod
    def get(self, function_id: str, version: int) -> Optional[Function]:
        """The one Function version, keyed the same way the Mongo doc's _id
        is (f"{function_id}:{version}")."""

    @abstractmethod
    def apply_event_data(self, data: Dict[str, Any]) -> None: ...

    @abstractmethod
    def mark_deleted_from_event(self, data: Dict[str, Any]) -> None: ...

    @abstractmethod
    def detach_endpoint_from_event(self, data: Dict[str, Any]) -> None:
        """Removes one endpoint_id from this function version's list
        (FunctionEndpointDetached) -- used when that endpoint is purged but
        other endpoints still hold the function, so it isn't soft-deleted."""

    @abstractmethod
    def list_by_endpoint_id(self, endpoint_id: str) -> List[Function]:
        """Every not-yet-soft-deleted function version this endpoint is one
        of the current holders of (deleted_at is None) -- already-deleted
        versions are excluded, since the only caller has no use for them."""
