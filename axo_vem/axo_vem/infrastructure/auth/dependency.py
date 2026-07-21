from __future__ import annotations

from typing import Callable, Optional, Union

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from xolo.client import XoloClient
from xolo.client.models import UserDTO

from axo_vem.domain.identity.repository import UserProfileRepository
from axo_vem.log import DumbLogger, Log
from axo_vem.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]

# Declared at module scope (not built ad hoc inside a Header(...) default)
# so FastAPI's generated OpenAPI schema carries them as named
# securitySchemes -- that's what makes Swagger UI show a lock icon and an
# "Authorize" dialog for every route gated behind them, which plain
# Header(...) dependencies never trigger. auto_error=False on both: a
# missing/invalid credential should reach get_current_user's own 401, not a
# generic FastAPI-generated error before the Xolo round trip.
bearer_scheme = HTTPBearer(auto_error=False)
temporal_key_scheme = APIKeyHeader(name="Temporal-Secret-Key", auto_error=False)


def build_identity_dependency(
    xolo_client: XoloClient,
    logger: _Logger = None,
) -> Callable[..., UserDTO]:
    """Returns a FastAPI dependency resolving the caller's xolo UserDTO from
    the Authorization: Bearer token plus the optional Temporal-Secret-Key
    header.

    Xolo sessions are (access_token, temporal_secret) pairs, not plain
    bearer JWTs (see xolo.client.client.XoloClient.get_current_user) -- but
    the token itself is always mandatory there (XoloClient raises if it's
    blank), so a request carrying only a Temporal-Secret-Key and no bearer
    token can never be verified and is rejected here before ever reaching
    XoloClient, rather than forwarded as token="".

    Does not check for a local UserProfile -- used directly by the one
    route (POST /profile) that must keep working before a profile exists
    yet. Everything else should depend on build_current_user_dependency
    below instead.
    """
    _logger: _Logger = logger or DumbLogger()

    def get_current_identity(
        bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
        temporal_secret: Optional[str] = Security(temporal_key_scheme),
    ) -> UserDTO:
        if bearer is None:
            raise HTTPException(
                status_code=401,
                detail="expected an Authorization: Bearer <token> header",
            )

        result = xolo_client.get_current_user(bearer.credentials, temporal_secret or "")
        if result.is_err:
            err = result.unwrap_err()
            _logger.warning_event(
                Event.Auth.UNAUTHORIZED,
                component=Component.AUTH,
                error_code=err.detail.code,
                status_code=err.detail.status_code,
            )
            raise HTTPException(status_code=err.detail.status_code, detail=err.detail.message)
        return result.unwrap()

    return get_current_identity


def build_current_user_dependency(
    xolo_client: XoloClient,
    user_profile_repository: UserProfileRepository,
    logger: _Logger = None,
) -> Callable[..., UserDTO]:
    """Returns the full get_current_user dependency every restricted router
    is gated behind: Xolo identity verification (401 on failure or a
    missing bearer token, via build_identity_dependency above) plus a local
    UserProfile existence check (404 if the verified identity has no
    profile in Mongo yet -- e.g. it was never signed up through POST
    /signup or POST /profile)."""
    identity_dependency = build_identity_dependency(xolo_client, logger=logger)

    def get_current_user(
        current_identity: UserDTO = Depends(identity_dependency),
    ) -> UserDTO:
        if user_profile_repository.get_by_user_id(current_identity.key) is None:
            raise HTTPException(status_code=404, detail="profile not found")
        return current_identity

    return get_current_user
