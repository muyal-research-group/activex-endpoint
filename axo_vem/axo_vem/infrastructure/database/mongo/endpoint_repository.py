from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo.collection import Collection

from axo_vem.domain.compute.endpoint import Endpoint
from axo_vem.domain.compute.repository import EndpointRepository


class MongoEndpointRepository(EndpointRepository):
    """Write access for Endpoint aggregates -- absorbs
    projector/upserts.py's former upsert_endpoint. GET routes for endpoints
    stay dict-based against this same collection (see
    infrastructure/transport/api/controllers/endpoints.py), since no event
    today carries a complete Endpoint shape (see domain/compute/endpoint.py's
    docstring) -- server.py passes the same underlying pymongo Collection to
    both this repository and the GET controller.
    """

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def _doc_to_endpoint(self, doc: Dict[str, Any]) -> Endpoint:
        return Endpoint(
            endpoint_id=doc["_id"],
            router_bind=doc.get("router_bind"),
            pub_bind=doc.get("pub_bind"),
            status=doc.get("status"),
            virtual_environment_id=doc.get("virtual_environment_id"),
            last_seen_at=doc.get("created_at"),
        )

    def save(self, endpoint: Endpoint) -> None:
        data: Dict[str, Any] = {}
        if endpoint.router_bind is not None:
            data["router_bind"] = endpoint.router_bind
        self._collection.update_one({"_id": endpoint.endpoint_id}, {"$set": data}, upsert=True)

    def get(self, endpoint_id: str) -> Optional[Endpoint]:
        doc = self._collection.find_one({"_id": endpoint_id})
        if doc is None:
            return None
        return self._doc_to_endpoint(doc)

    def apply_event_data(self, endpoint_id: str, data: Dict[str, Any]) -> None:
        """Plain $set upsert of one event's full field set -- EndpointStarted,
        EndpointMetricsReported, EndpointStopped,
        EndpointVirtualEnvironmentAssigned/Detached are all safe to replay
        under at-least-once redelivery this way, exactly like
        projector/upserts.py's former upsert_endpoint(collection, endpoint_id, data)."""
        self._collection.update_one({"_id": endpoint_id}, {"$set": data}, upsert=True)

    def list_by_virtual_environment(self, virtual_environment_id: str) -> List[Endpoint]:
        """Ordered most-recently-seen first (last_seen_at desc, i.e. the doc's
        `created_at` from whichever EndpointStarted/MetricsReported/Stopped
        event landed most recently), tie-broken by endpoint_id ascending for
        determinism. EndpointVirtualEnvironmentDetached's event leaves
        virtual_environment_id at its EventEnvelope default of None, so a
        detached endpoint's doc is correctly excluded here without any extra
        filtering."""
        docs = self._collection.find(
            {"virtual_environment_id": virtual_environment_id}
        ).sort([("created_at", -1), ("_id", 1)])
        return [self._doc_to_endpoint(doc) for doc in docs]
