from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from xolo.client.models import UserDTO

from axo_vem.domain.errors import NotFoundError
from axo_vem.domain.identity.repository import UserProfileRepository
from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository

_DEFAULT_ACTIVITY_WINDOW_MINUTES = 60


def build_router(
    activity_repository: MongoActivityRepository,
    virtual_environment_repository: Optional[VirtualEnvironmentRepository],
    current_user_dependency: Callable[..., UserDTO],
    user_profile_repository: Optional[UserProfileRepository] = None,
) -> APIRouter:
    """Reads from unified_activity -- one catch-all timeline plus one
    per-entity-scoped view apiece. Every route here requires
    current_user_dependency; the two that shadow an already-access-controlled
    entity (a user's own profile, a virtual environment's owner) additionally
    check ownership so a logged-in user still can't enumerate another user's
    profile history or another tenant's virtual-environment history by
    guessing ids. The virtual-environment check now goes through
    VirtualEnvironment.assert_owner() (raises NotOwnerError, translated to
    403 by the registered exception handler) instead of an inline dict
    comparison; the user-profile check has no aggregate to check against
    (it's a plain path-param-vs-caller comparison), so it stays a direct
    HTTPException."""
    router = APIRouter()  # no router-level default tag: each route below needs its own

    def _since_for(current_user: UserDTO) -> datetime:
        """Resolves the caller's activity_window_minutes preference (falling
        back to the default for a caller with no profile yet, or when this
        deployment wasn't wired with a user_profile_repository at all) into
        an absolute cutoff. Purely a display default -- independent of
        AXO_VEM_ACTIVITY_RETENTION_HOURS's actual server-side
        retention ceiling, which the background worker enforces separately."""
        window_minutes = _DEFAULT_ACTIVITY_WINDOW_MINUTES
        if user_profile_repository is not None:
            profile = user_profile_repository.get_by_user_id(current_user.key)
            if profile is not None:
                window_minutes = profile.preferences.activity_window_minutes
        return datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    @router.get("/history", tags=["job telemetry"])
    def get_history(
        user_id: Optional[str] = None,
        virtual_environment_id: Optional[str] = None,
        endpoint_id: Optional[str] = None,
        function_id: Optional[str] = None,
        active_object_id: Optional[str] = None,
        limit: int = 100,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        return activity_repository.get_timeline(
            user_id=user_id,
            virtual_environment_id=virtual_environment_id,
            endpoint_id=endpoint_id,
            function_id=function_id,
            active_object_id=active_object_id,
            since=_since_for(current_user),
            limit=limit,
        )

    @router.get("/endpoints/{endpoint_id}/history", tags=["endpoint management"])
    def get_endpoint_history(
        endpoint_id: str, limit: int = 100, current_user: UserDTO = Depends(current_user_dependency),
    ):
        return activity_repository.get_timeline(endpoint_id=endpoint_id, since=_since_for(current_user), limit=limit)

    @router.get("/functions/{function_id}/history", tags=["function registries"])
    def get_function_history(
        function_id: str, limit: int = 100, current_user: UserDTO = Depends(current_user_dependency),
    ):
        return activity_repository.get_timeline(function_id=function_id, since=_since_for(current_user), limit=limit)

    @router.get("/active-objects/{active_object_id}/history", tags=["active objects"])
    def get_active_object_history(
        active_object_id: str, limit: int = 100, current_user: UserDTO = Depends(current_user_dependency),
    ):
        return activity_repository.get_timeline(
            active_object_id=active_object_id, since=_since_for(current_user), limit=limit,
        )

    @router.get("/user-profiles/{user_id}/history", tags=["user profile"])
    def get_user_profile_history(
        user_id: str,
        limit: int = 100,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        if user_id != current_user.key:
            raise HTTPException(status_code=403, detail="not the owner of this profile")
        return activity_repository.get_timeline(user_id=user_id, since=_since_for(current_user), limit=limit)

    if virtual_environment_repository is not None:

        @router.get("/virtual-environments/{virtual_environment_id}/history", tags=["virtual environment"])
        def get_virtual_environment_history(
            virtual_environment_id: str,
            limit: int = 100,
            current_user: UserDTO = Depends(current_user_dependency),
        ):
            virtual_environment = virtual_environment_repository.get(virtual_environment_id)
            if virtual_environment is None:
                raise NotFoundError("virtual environment not found")
            virtual_environment.assert_owner(current_user.key)
            return activity_repository.get_timeline(
                virtual_environment_id=virtual_environment_id, since=_since_for(current_user), limit=limit,
            )

    return router
