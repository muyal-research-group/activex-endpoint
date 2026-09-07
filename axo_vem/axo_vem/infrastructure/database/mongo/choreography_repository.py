from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo.collection import Collection

from axo_vem.domain.choreography.choreography import Choreography
from axo_vem.domain.choreography.repository import ChoreographyRepository
from axo_vem.domain.events.models import ChoreographyGraph


def _doc_to_choreography(doc: Dict[str, Any]) -> Choreography:
    return Choreography(
        choreography_id=doc["choreography_id"],
        name=doc["name"],
        owner_user_id=doc["owner_user_id"],
        graph=ChoreographyGraph.model_validate(doc["graph"]),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


class MongoChoreographyRepository(ChoreographyRepository):
    """Read/write access to the `choreographies` collection -- mirrors
    MongoVirtualEnvironmentRepository's bespoke-repository shape (soft
    delete via deleted_at, filtered out of every read here)."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get(self, choreography_id: str) -> Optional[Choreography]:
        doc = self._collection.find_one({"_id": choreography_id})
        if doc is None or doc.get("deleted_at") is not None:
            return None
        return _doc_to_choreography(doc)

    def list(self, owner_user_id: Optional[str] = None) -> List[Choreography]:
        query: Dict[str, Any] = {"deleted_at": None}
        if owner_user_id is not None:
            query["owner_user_id"] = owner_user_id
        return [_doc_to_choreography(doc) for doc in self._collection.find(query)]

    def save(self, choreography: Choreography) -> None:
        data = {
            "choreography_id": choreography.choreography_id,
            "name": choreography.name,
            "owner_user_id": choreography.owner_user_id,
            "graph": choreography.graph.model_dump(mode="json"),
            "created_at": choreography.created_at,
            "updated_at": choreography.updated_at,
        }
        self._collection.update_one({"_id": choreography.choreography_id}, {"$set": data}, upsert=True)

    def soft_delete(self, choreography_id: str, deleted_at) -> None:
        self._collection.update_one({"_id": choreography_id}, {"$set": {"deleted_at": deleted_at}})
