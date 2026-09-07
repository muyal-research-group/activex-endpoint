from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo.collection import Collection

from axo_vem.domain.compute.function import Function
from axo_vem.domain.compute.repository import FunctionRepository


class MongoFunctionRepository(FunctionRepository):
    """Write access for Function entities -- absorbs projector/upserts.py's
    former upsert_function/mark_function_deleted. GET routes for functions
    stay dict-based against this same collection (see
    infrastructure/transport/api/controllers/functions.py), for the same
    reason documented on MongoEndpointRepository."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def save(self, function: Function) -> None:
        key = f"{function.function_id}:{function.version}"
        data = {"function_id": function.function_id, "version": function.version}
        if function.runtime_spec is not None:
            data["runtime_spec"] = function.runtime_spec
        if function.owner_user_id is not None:
            data["owner_user_id"] = function.owner_user_id
        update: Dict[str, Any] = {"$set": data}
        if function.endpoint_id:
            update["$addToSet"] = {"endpoint_id": {"$each": function.endpoint_id}}
        self._collection.update_one({"_id": key}, update, upsert=True)

    def get(self, function_id: str, version: int) -> Optional[Function]:
        doc = self._collection.find_one({"_id": f"{function_id}:{version}"})
        if doc is None:
            return None
        return Function(
            function_id=doc["function_id"],
            version=doc["version"],
            runtime_spec=doc.get("runtime_spec"),
            owner_user_id=doc.get("owner_user_id"),
            deleted_at=doc.get("deleted_at"),
            endpoint_id=doc.get("endpoint_id") or [],
            virtual_environment_id=doc.get("virtual_environment_id"),
            container_status=doc.get("container_status"),
        )

    def mark_deleted(self, function_id: str, version: int, deleted_at) -> None:
        key = f"{function_id}:{version}"
        self._collection.update_one({"_id": key}, {"$set": {"deleted_at": deleted_at}}, upsert=True)

    def apply_event_data(self, data: Dict[str, Any]) -> None:
        """Plain $set upsert of one event's full field set, keyed by
        f"{function_id}:{version}" -- trusts in-order delivery per function
        (a single function's events are appended by a single leader-owned
        stream) rather than adding a timestamp guard. Mirrors
        projector/upserts.py's former upsert_function(collection, data).

        endpoint_id is handled separately via $addToSet rather than folded
        into the $set: every function-lifecycle event that carries it
        (FunctionRegistered from the origin node, FunctionRegistered
        re-forwarded by a follower absorbing a replica, FunctionUpdated,
        FunctionDeployed, ...) is "this node has/still has the record," not
        "this is now the only node that has it" -- so repeated arrivals
        must accumulate into a set, never overwrite it."""
        key = f"{data['function_id']}:{data['version']}"
        data = dict(data)
        endpoint_id = data.pop("endpoint_id", None)
        update: Dict[str, Any] = {"$set": data}
        if endpoint_id is not None:
            update["$addToSet"] = {"endpoint_id": endpoint_id}
        self._collection.update_one({"_id": key}, update, upsert=True)

    def mark_deleted_from_event(self, data: Dict[str, Any]) -> None:
        """Mirrors projector/upserts.py's former mark_function_deleted:
        marks deleted_at rather than removing the document -- keeps past
        Job*/unified_activity records correlated against this function id
        still resolvable."""
        key = f"{data['function_id']}:{data['version']}"
        self._collection.update_one({"_id": key}, {"$set": {"deleted_at": data["created_at"]}}, upsert=True)

    def detach_endpoint_from_event(self, data: Dict[str, Any]) -> None:
        """Removes one endpoint_id from the array (FunctionEndpointDetached)
        -- used instead of mark_deleted_from_event when other endpoints
        still hold this function version."""
        key = f"{data['function_id']}:{data['version']}"
        self._collection.update_one({"_id": key}, {"$pull": {"endpoint_id": data["endpoint_id"]}})

    def list_by_endpoint_id(self, endpoint_id: str) -> List[Function]:
        # Equality match against an array field means "array contains" in
        # Mongo, so this needs no change for endpoint_id's string -> list migration.
        docs = self._collection.find({"endpoint_id": endpoint_id, "deleted_at": None})
        return [
            Function(
                function_id=doc["function_id"],
                version=doc["version"],
                runtime_spec=doc.get("runtime_spec"),
                owner_user_id=doc.get("owner_user_id"),
                deleted_at=doc.get("deleted_at"),
                endpoint_id=doc.get("endpoint_id") or [],
                virtual_environment_id=doc.get("virtual_environment_id"),
                container_status=doc.get("container_status"),
            )
            for doc in docs
        ]
