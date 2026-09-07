from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from xolo.client import XoloClient
from xolo.client.models import UserDTO

from axo_vem.application.identity.create_profile import CreateProfileUseCase
from axo_vem.application.identity.delete_profile import DeleteProfileUseCase
from axo_vem.application.identity.signup import SignupUseCase
from axo_vem.application.identity.update_profile import UpdateProfileUseCase
from axo_vem.domain.errors import NotFoundError
from axo_vem.domain.identity.repository import UserProfileRepository


class _ProfileRequest(BaseModel):
    profile_photo: str = ""
    color: Optional[str] = None
    view_mode: str = "list"
    language: str = "en"
    activity_window_minutes: int = 60
    endpoint_purge_eligible_after_minutes: int = 60


class _SignupRequest(BaseModel):
    username: str
    first_name: str
    last_name: str
    email: str
    password: str
    scope: str = "axo"
    profile_photo: str = ""
    expiration: str = "1y"
    color: Optional[str] = None
    view_mode: str = "list"
    language: str = "en"
    activity_window_minutes: int = 60
    endpoint_purge_eligible_after_minutes: int = 60


class _LoginRequest(BaseModel):
    username: str
    password: str
    scope: str = "axo"
    expiration: str = "1h"
    renew_token: bool = False


def build_router(
    repository: UserProfileRepository,
    signup_use_case: SignupUseCase,
    create_profile_use_case: CreateProfileUseCase,
    update_profile_use_case: UpdateProfileUseCase,
    delete_profile_use_case: DeleteProfileUseCase,
    current_user_dependency: Callable[..., UserDTO],
    identity_dependency: Callable[..., UserDTO],
    xolo_client: XoloClient,
) -> APIRouter:
    router = APIRouter(tags=["user profile"])

    @router.post("/signup", status_code=201)
    def signup(body: _SignupRequest):
        """Public: provisions the external Xolo identity, then maps the
        returned id to a local UserProfile -- signup is the primary path a
        new UserProfile comes into existence through; POST /profile below
        exists only for identities that were provisioned some other way
        (e.g. XoloClient.create_user through the admin API)."""
        result = signup_use_case.execute(
            username=body.username,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            password=body.password,
            scope=body.scope,
            profile_photo=body.profile_photo,
            expiration=body.expiration,
            color=body.color,
            view_mode=body.view_mode,
            language=body.language,
            activity_window_minutes=body.activity_window_minutes,
            endpoint_purge_eligible_after_minutes=body.endpoint_purge_eligible_after_minutes,
        )
        if result.is_err:
            err = result.unwrap_err()
            raise HTTPException(status_code=err.detail.status_code, detail=err.detail.message)
        return result.unwrap()

    @router.post("/login")
    def login(body: _LoginRequest):
        """Public: a thin proxy to Xolo's own auth endpoint, returning the
        (access_token, temporal_secret) session pair the caller then sends
        back as Authorization: Bearer / Temporal-Secret-Key on every
        subsequent request. No domain logic here -- stays a direct Xolo
        passthrough rather than an application use case."""
        result = xolo_client.auth(
            username=body.username,
            password=body.password,
            scope="axo",
            expiration=body.expiration,
            renew_token=body.renew_token,
        )
        if result.is_err:
            err = result.unwrap_err()
            raise HTTPException(status_code=err.detail.status_code, detail=err.detail.message)
        return result.unwrap().model_dump(mode="json")

    @router.get("/profile")
    def get_profile(current_user: UserDTO = Depends(current_user_dependency)):
        profile = repository.get_by_user_id(current_user.key)
        if profile is None:
            raise HTTPException(status_code=404, detail="profile not found")
        return profile.to_dict()

    @router.post("/profile", status_code=201)
    def create_profile(
        body: _ProfileRequest,
        current_user: UserDTO = Depends(identity_dependency),
    ):
        return create_profile_use_case.execute(
            user_id=current_user.key,
            profile_photo=body.profile_photo,
            color=body.color,
            view_mode=body.view_mode,
            language=body.language,
            activity_window_minutes=body.activity_window_minutes,
            endpoint_purge_eligible_after_minutes=body.endpoint_purge_eligible_after_minutes,
        )

    @router.put("/profile")
    def update_profile(
        body: _ProfileRequest,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        return update_profile_use_case.execute(
            user_id=current_user.key,
            profile_photo=body.profile_photo,
            color=body.color,
            view_mode=body.view_mode,
            language=body.language,
            activity_window_minutes=body.activity_window_minutes,
            endpoint_purge_eligible_after_minutes=body.endpoint_purge_eligible_after_minutes,
        )

    @router.delete("/profile", status_code=204)
    def delete_profile(current_user: UserDTO = Depends(current_user_dependency)):
        delete_profile_use_case.execute(user_id=current_user.key)
        return None

    return router
