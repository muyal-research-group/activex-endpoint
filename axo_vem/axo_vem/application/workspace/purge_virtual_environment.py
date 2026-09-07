from __future__ import annotations

from pymongo.collection import Collection

from axo_vem.domain.errors import ConflictError, NotFoundError, NotOwnerError
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository


class PurgeVirtualEnvironmentUseCase:
    """Hard-deletes a virtual environment's read-model doc and its
    unified_activity history -- distinct from DeleteVirtualEnvironmentUseCase
    (which only soft-deletes via VirtualEnvironmentDeleted). Requires the VE
    to already be soft-deleted; never touches the underlying Kurrent event
    log. Reads the raw collection directly rather than through
    VirtualEnvironmentRepository.get(), which filters out soft-deleted docs
    -- exactly the state this guard needs to detect."""

    def __init__(self, virtual_environments: Collection, activity_repository: MongoActivityRepository) -> None:
        self._virtual_environments = virtual_environments
        self._activity_repository = activity_repository

    def execute(self, *, virtual_environment_id: str, current_user_id: str) -> None:
        doc = self._virtual_environments.find_one({"_id": virtual_environment_id})
        if doc is None:
            raise NotFoundError("virtual environment not found")
        if doc.get("owner_user_id") != current_user_id:
            raise NotOwnerError("caller does not own this virtual environment")
        if doc.get("deleted_at") is None:
            raise ConflictError("virtual environment must be deleted first")

        self._virtual_environments.delete_one({"_id": virtual_environment_id})
        self._activity_repository.purge(virtual_environment_id=virtual_environment_id)
