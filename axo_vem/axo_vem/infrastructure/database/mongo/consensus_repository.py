from __future__ import annotations

from typing import Any, Dict, Optional

from pymongo.collection import Collection

from axo_vem.domain.compute.consensus_recorder import ConsensusRecorder


class MongoConsensusRepository(ConsensusRecorder):
    """Write access for cluster-consensus facts, keyed by term (not a
    singleton) -- sidesteps races between endpoints independently reporting
    the same term via Bully. "Current leader" = highest _id, queried
    directly by infrastructure/transport/api/controllers/consensus.py
    against this same collection, unchanged from today. Absorbs
    projector/upserts.py's former upsert_consensus."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def record(self, endpoint_id: str, data: Dict[str, Any]) -> None:
        term = data["term"]
        self._collection.update_one(
            {"_id": term},
            {"$set": data, "$addToSet": {"reported_by": endpoint_id}},
            upsert=True,
        )
