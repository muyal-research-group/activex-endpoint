from __future__ import annotations

from typing import Optional

from pymongo.collection import Collection

_CHECKPOINT_ID = "main"


class MongoCheckpointStore:
    """Remembers the last Kurrent commit position this projector has fully
    applied, in a single document in its own collection -- so a restart
    resumes instead of replaying everything or missing events. Written as a
    plain sequential update after each upsert (not a multi-document
    transaction): correctness here relies on every upsert being idempotent
    (see application/projector/dispatcher.py), not on checkpoint/upsert
    atomicity, so a standalone mongo instance (no replica set) is
    sufficient. Moved verbatim from projector/checkpoint.py.
    """

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get_position(self) -> Optional[int]:
        """None means "no checkpoint yet" -- the projector should subscribe
        from the very start of the $all stream."""
        doc = self._collection.find_one({"_id": _CHECKPOINT_ID})
        return doc["position"] if doc else None

    def set_position(self, position: int) -> None:
        self._collection.update_one(
            {"_id": _CHECKPOINT_ID}, {"$set": {"position": position}}, upsert=True,
        )
