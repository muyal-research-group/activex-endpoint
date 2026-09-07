from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo.collection import Collection

from axo_vem.domain.choreography.run import ACTIVE_RUN_STATUSES, ChoreographyRun, NodeRunState
from axo_vem.domain.choreography.run_repository import ChoreographyRunRepository


def _doc_to_run(doc: Dict[str, Any]) -> ChoreographyRun:
    return ChoreographyRun(
        run_id=doc["run_id"],
        choreography_id=doc["choreography_id"],
        status=doc["status"],
        node_states={
            node_id: NodeRunState(node_id=node_id, **{k: v for k, v in state.items() if k != "node_id"})
            for node_id, state in doc.get("node_states", {}).items()
        },
        started_at=doc.get("started_at"),
        finished_at=doc.get("finished_at"),
    )


class MongoChoreographyRunRepository(ChoreographyRunRepository):
    """Read/write access to the `choreography_runs` collection -- one
    document per run (see ChoreographyRun's docstring for why this is a
    plain store, not event-sourced)."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get(self, run_id: str) -> Optional[ChoreographyRun]:
        doc = self._collection.find_one({"_id": run_id})
        return _doc_to_run(doc) if doc is not None else None

    def list_by_choreography(self, choreography_id: str) -> List[ChoreographyRun]:
        docs = self._collection.find({"choreography_id": choreography_id}).sort("started_at", -1)
        return [_doc_to_run(doc) for doc in docs]

    def has_active_run(self, choreography_id: str) -> bool:
        return self._collection.count_documents({
            "choreography_id": choreography_id,
            "status": {"$in": list(ACTIVE_RUN_STATUSES)},
        }) > 0

    def save(self, run: ChoreographyRun) -> None:
        data = {
            "run_id": run.run_id,
            "choreography_id": run.choreography_id,
            "status": run.status,
            "node_states": {node_id: ns.to_dict() for node_id, ns in run.node_states.items()},
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
        self._collection.update_one({"_id": run.run_id}, {"$set": data}, upsert=True)
