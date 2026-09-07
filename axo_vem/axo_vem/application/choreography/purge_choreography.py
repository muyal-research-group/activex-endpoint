from __future__ import annotations

from pymongo.collection import Collection

from axo_vem.domain.errors import ConflictError, NotFoundError, NotOwnerError
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository


class PurgeChoreographyUseCase:
    """Hard-deletes a choreography's read-model doc, its run history, and
    its unified_activity rows -- mirrors PurgeVirtualEnvironmentUseCase.
    Requires the choreography to already be soft-deleted; never touches the
    underlying Kurrent event log."""

    def __init__(
        self,
        choreographies: Collection,
        choreography_runs: Collection,
        activity_repository: MongoActivityRepository,
    ) -> None:
        self._choreographies = choreographies
        self._choreography_runs = choreography_runs
        self._activity_repository = activity_repository

    def execute(self, *, choreography_id: str, current_user_id: str) -> None:
        doc = self._choreographies.find_one({"_id": choreography_id})
        if doc is None:
            raise NotFoundError("choreography not found")
        if doc.get("owner_user_id") != current_user_id:
            raise NotOwnerError("caller does not own this choreography")
        if doc.get("deleted_at") is None:
            raise ConflictError("choreography must be deleted first")

        self._choreographies.delete_one({"_id": choreography_id})
        self._choreography_runs.delete_many({"choreography_id": choreography_id})
        self._activity_repository.purge(choreography_id=choreography_id)
