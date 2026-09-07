from __future__ import annotations

from typing import Any, Dict, Optional

from pymongo.collection import Collection

from axo_vem.domain.errors import ConflictError, NotFoundError
from axo_vem.domain.events.stream_admin import StreamAdmin
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository


class PurgeFunctionVersionUseCase:
    """Hard-deletes this function version's read-model doc and its
    unified_activity history, and permanently deletes its isolated Kurrent
    stream (functions-{function_id}-{version} -- distinct per version
    precisely so this can't destroy a sibling version's history). Distinct
    from DeleteFunctionUseCase (which only soft-deletes via
    FUNCTION_DELETE/FunctionDeleted). Requires the version to already be
    soft-deleted. stream_admin is optional so tests/deployments without a
    live Kurrent connection can still exercise the Mongo/activity side.

    Reads the raw collection directly rather than through
    FunctionRepository.get() -- same rationale as
    PurgeVirtualEnvironmentUseCase: this is a pure lift of the former inline
    route body, no behavior change."""

    def __init__(
        self,
        functions: Collection,
        activity_repository: MongoActivityRepository,
        stream_admin: Optional[StreamAdmin] = None,
    ) -> None:
        self._functions = functions
        self._activity_repository = activity_repository
        self._stream_admin = stream_admin

    def execute(self, *, function_id: str, version: int) -> Dict[str, Any]:
        key = f"{function_id}:{version}"
        doc = self._functions.find_one({"_id": key})
        if doc is None:
            raise NotFoundError("function version not found")
        if doc.get("deleted_at") is None:
            raise ConflictError("function version is not deleted yet")

        self._functions.delete_one({"_id": key})
        purged = self._activity_repository.purge(function_id=function_id, function_version=version)
        if self._stream_admin is not None:
            self._stream_admin.delete_stream(f"functions-{function_id}-{version}")
        return {"function_id": function_id, "version": version, "purged_activity_count": purged}
