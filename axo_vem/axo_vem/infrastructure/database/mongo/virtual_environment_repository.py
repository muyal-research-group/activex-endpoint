from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pymongo.collection import Collection

from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository
from axo_vem.domain.workspace.value_objects import ResourceCapacity
from axo_vem.domain.workspace.virtual_environment import VirtualEnvironment


def _doc_to_virtual_environment(doc: Dict[str, Any]) -> VirtualEnvironment:
    quota = doc.get("resource_quota") or {}
    return VirtualEnvironment(
        virtual_environment_id=doc["virtual_environment_id"],
        name=doc["name"],
        owner_user_id=doc["owner_user_id"],
        capacity=ResourceCapacity(cpu=quota["cpu"], ram=quota["ram"], disk=quota["disk"]),
        leader_endpoint_id=doc.get("leader_endpoint_id"),
    )


class MongoVirtualEnvironmentRepository(VirtualEnvironmentRepository):
    """Read/write access to the virtual_environments collection -- a
    bespoke, single-purpose repository (not the generic Repository[T],
    whose list_by_function_id shape doesn't fit this aggregate), same
    rationale the old repository/virtual_environment.py documented.
    Soft-deleted documents (deleted_at set) are filtered out of every read
    here. save()/soft_delete() absorb projector/upserts.py's former
    upsert_virtual_environment/soft_delete_virtual_environment.
    """

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get(self, virtual_environment_id: str) -> Optional[VirtualEnvironment]:
        doc = self._collection.find_one({"_id": virtual_environment_id})
        if doc is None or doc.get("deleted_at") is not None:
            return None
        return _doc_to_virtual_environment(doc)

    def list(self, owner_user_id: Optional[str] = None) -> List[VirtualEnvironment]:
        query: Dict[str, Any] = {"deleted_at": None}
        if owner_user_id is not None:
            query["owner_user_id"] = owner_user_id
        return [_doc_to_virtual_environment(doc) for doc in self._collection.find(query)]

    def search_by_name(self, name: str, owner_user_id: Optional[str] = None) -> List[VirtualEnvironment]:
        query: Dict[str, Any] = {
            "name": {"$regex": re.escape(name), "$options": "i"},
            "deleted_at": None,
        }
        if owner_user_id is not None:
            query["owner_user_id"] = owner_user_id
        return [_doc_to_virtual_environment(doc) for doc in self._collection.find(query)]

    def save(self, virtual_environment: VirtualEnvironment) -> None:
        data = {
            "virtual_environment_id": virtual_environment.virtual_environment_id,
            "name": virtual_environment.name,
            "owner_user_id": virtual_environment.owner_user_id,
            "resource_quota": {
                "cpu": virtual_environment.capacity.cpu,
                "ram": virtual_environment.capacity.ram,
                "disk": virtual_environment.capacity.disk,
            },
        }
        self._collection.update_one(
            {"_id": virtual_environment.virtual_environment_id}, {"$set": data}, upsert=True,
        )

    def soft_delete(self, virtual_environment_id: str, deleted_at) -> None:
        """Marks deleted_at rather than removing the document -- keeps the
        read model queryable against Kurrent's full history instead of
        losing it. get()/list()/search_by_name() filter out documents with
        deleted_at set."""
        self._collection.update_one(
            {"_id": virtual_environment_id}, {"$set": {"deleted_at": deleted_at}},
        )

    def set_leader_endpoint_id(self, virtual_environment_id: str, leader_endpoint_id: str) -> None:
        # No upsert -- a VE doc must already exist (via VirtualEnvironmentCreated)
        # with its required name/owner_user_id/resource_quota fields, or
        # _doc_to_virtual_environment() would KeyError on a half-populated doc.
        self._collection.update_one(
            {"_id": virtual_environment_id, "deleted_at": None},
            {"$set": {"leader_endpoint_id": leader_endpoint_id}},
        )

    def clear_leader_endpoint_id(self) -> None:
        self._collection.update_many(
            {"leader_endpoint_id": {"$exists": True}}, {"$unset": {"leader_endpoint_id": ""}},
        )
