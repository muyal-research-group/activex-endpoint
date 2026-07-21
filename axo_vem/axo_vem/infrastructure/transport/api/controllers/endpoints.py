from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo.collection import Collection
from xolo.client.models import UserDTO

from axo_shared import wire
from axo_shared.protocol import Command

from axo_vem.application.nodes.deployment_defaults import DEPLOYMENT_DEFAULTS
from axo_vem.application.nodes.launch_endpoint_node import LaunchEndpointNodeUseCase
from axo_vem.application.nodes.purge_endpoint import PurgeEndpointUseCase
from axo_vem.application.nodes.restart_endpoint_node import RestartEndpointNodeUseCase
from axo_vem.application.nodes.stop_endpoint_node import StopEndpointNodeUseCase
from axo_vem.domain.identity.repository import UserProfileRepository
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository
from axo_vem.infrastructure.transport.api.serialization import strip_id
from axo_vem.infrastructure.transport.zmq_command.endpoint_client import resolve_rpc_uri, send_command


def _parse_iso(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class _VirtualEnvAssignRequest(BaseModel):
    virtual_environment_id: Optional[str] = None


class _EndpointDeployRequest(BaseModel):
    virtual_environment_id: Optional[str] = None
    env_overrides: Dict[str, str] = {}
    router_port: int = 5555
    pub_port: int = 5556
    results_port: int = 5557


def build_router(
    endpoints: Collection,
    current_user_dependency: Callable[..., UserDTO],
    activity_repository: MongoActivityRepository,
    command_timeout_seconds: float = 3.0,
    launch_endpoint_node_use_case: Optional[LaunchEndpointNodeUseCase] = None,
    node_api_uri: Optional[str] = None,
    stop_endpoint_node_use_case: Optional[StopEndpointNodeUseCase] = None,
    restart_endpoint_node_use_case: Optional[RestartEndpointNodeUseCase] = None,
    user_profile_repository: Optional[UserProfileRepository] = None,
    purge_eligible_after_minutes_default: int = 60,
    purge_endpoint_use_case: Optional[PurgeEndpointUseCase] = None,
) -> APIRouter:
    router = APIRouter(tags=["endpoint management"])

    def _purge_eligible_after_for(current_user: UserDTO) -> int:
        """Resolves the caller's endpoint_purge_eligible_after_minutes
        preference, falling back to purge_eligible_after_minutes_default
        (sourced from AXO_VEM_ENDPOINT_PURGE_ELIGIBLE_AFTER_MINUTES, see
        config.py) for a caller with no profile yet, or when this
        deployment wasn't wired with a user_profile_repository at all.
        Purely a UI-surfacing default -- the actual purge gate below never
        consults this, mirrors history.py's _since_for."""
        minutes = purge_eligible_after_minutes_default
        if user_profile_repository is not None:
            profile = user_profile_repository.get_by_user_id(current_user.key)
            if profile is not None:
                minutes = profile.preferences.endpoint_purge_eligible_after_minutes
        return minutes

    def _decorate(doc: Dict[str, Any], current_user: UserDTO) -> Dict[str, Any]:
        """Adds computed, viewer-scoped purge_eligible/unreachable_since
        fields on top of the raw doc. unreachable_since is just the doc's
        own created_at read back out -- it gets $set to the
        EndpointUnreachable event's own created_at the moment status flips
        (see application/projector/compute_handler.py), not a separate
        stored field."""
        result = strip_id(doc)
        status = doc.get("status")
        if status == "stopped":
            result["purge_eligible"] = True
            result["unreachable_since"] = None
        elif status == "unreachable":
            since_raw = doc.get("created_at")
            since = _parse_iso(since_raw)
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=_purge_eligible_after_for(current_user))
            result["purge_eligible"] = since is not None and since <= cutoff
            result["unreachable_since"] = since_raw
        else:
            result["purge_eligible"] = False
            result["unreachable_since"] = None
        return result

    @router.get("/endpoints")
    def list_endpoints(current_user: UserDTO = Depends(current_user_dependency)):
        return [_decorate(doc, current_user) for doc in endpoints.find()]

    if launch_endpoint_node_use_case is not None and node_api_uri is not None:

        @router.get("/endpoints/deployment-defaults")
        def get_deployment_defaults(_current_user: UserDTO = Depends(current_user_dependency)):
            """Every AXO_ENDPOINT_* env var a node reads, with its default
            value -- a caller (e.g. a deploy form) pre-fills from this, then
            overrides any subset via POST /endpoints's env_overrides."""
            return DEPLOYMENT_DEFAULTS

        @router.post("/endpoints", status_code=201)
        def deploy_endpoint(
            body: _EndpointDeployRequest,
            _current_user: UserDTO = Depends(current_user_dependency),
        ):
            """Launches a new axo_endpoint node container via the shared
            ContainerSpawner -- does not write the read model itself, same
            as assign_virtual_environment below; the new node's own
            EndpointStarted event populates it once ingestion sees it.
            AXO_ENDPOINT_SUB_CONNECT is derived automatically by the use
            case from the target VE's existing running endpoints -- no
            caller-supplied peer list needed."""
            result = launch_endpoint_node_use_case.execute(
                api_uri=node_api_uri,
                router_port=body.router_port,
                pub_port=body.pub_port,
                results_port=body.results_port,
                virtual_environment_id=body.virtual_environment_id,
                env_overrides=body.env_overrides,
            )
            if result.is_err:
                raise HTTPException(status_code=502, detail=str(result.unwrap_err()))
            launched = result.unwrap()
            return {
                "endpoint_id": launched.endpoint_id,
                "container_name": launched.container_name,
                "router_bind": launched.router_bind,
            }

        @router.post("/endpoints/{endpoint_id}/stop")
        def stop_endpoint(endpoint_id: str, _current_user: UserDTO = Depends(current_user_dependency)):
            """Stops and removes the endpoint's container/service -- the
            read model updates asynchronously off the node's own
            EndpointStopped event, same as deploy_endpoint above. 404 if
            this API never launched a container/service under this
            endpoint_id (e.g. a docker-compose-managed node)."""
            result = stop_endpoint_node_use_case.execute(endpoint_id)
            if result.is_err:
                raise HTTPException(status_code=404, detail=str(result.unwrap_err()))
            return {"endpoint_id": endpoint_id, "status": "stopped"}

        @router.post("/endpoints/{endpoint_id}/restart")
        def restart_endpoint(endpoint_id: str, _current_user: UserDTO = Depends(current_user_dependency)):
            """Restarts the same container/service in place -- see
            stop_endpoint above for the read-model/reachability notes."""
            result = restart_endpoint_node_use_case.execute(endpoint_id)
            if result.is_err:
                raise HTTPException(status_code=404, detail=str(result.unwrap_err()))
            return {"endpoint_id": endpoint_id, "status": "restarted"}

    @router.get("/endpoints/{endpoint_id}")
    def get_endpoint(endpoint_id: str, current_user: UserDTO = Depends(current_user_dependency)):
        doc = endpoints.find_one({"_id": endpoint_id})
        if doc is None:
            raise HTTPException(status_code=404, detail="endpoint not found")
        return _decorate(doc, current_user)

    @router.post("/endpoints/{endpoint_id}/virtual-environment")
    def assign_virtual_environment(
        endpoint_id: str,
        body: _VirtualEnvAssignRequest,
        _current_user: UserDTO = Depends(current_user_dependency),
    ):
        """Sends VIRTUAL_ENV_ASSIGN straight to the endpoint (never
        proxied) and relays its CommandResult -- the read model itself
        is not written here; it only updates once the endpoint's own
        confirmation event arrives back through ingestion, same as
        everywhere else in this service."""
        doc = endpoints.find_one({"_id": endpoint_id})
        if doc is None:
            raise HTTPException(status_code=404, detail="endpoint not found")
        router_bind = doc.get("router_bind")
        if not router_bind:
            raise HTTPException(status_code=409, detail="endpoint has no known router_bind")
        rpc_uri = resolve_rpc_uri(router_bind, endpoint_id)

        command = Command(
            operation=wire.VIRTUAL_ENV_ASSIGN,
            content_type="application/json",
            envelope={"virtual_environment_id": body.virtual_environment_id},
        )
        result = send_command(rpc_uri, command, command_timeout_seconds)
        if result.is_err:
            raise HTTPException(status_code=504, detail=str(result.unwrap_err()))

        command_result = result.unwrap()
        if not command_result.ok:
            raise HTTPException(status_code=409, detail=command_result.error)
        return {"endpoint_id": endpoint_id, "virtual_environment_id": body.virtual_environment_id}

    @router.delete("/endpoints/{endpoint_id}/purge")
    def purge_endpoint(endpoint_id: str, _current_user: UserDTO = Depends(current_user_dependency)):
        """Hard-deletes this endpoint's read-model doc and its
        unified_activity history -- distinct from stop_endpoint above
        (which only stops/removes the node's container and lets
        EndpointStopped flip status). Requires the endpoint to already be
        stopped or unreachable (widened from stopped-only) -- an
        unreachable node is, for purge purposes, equally terminal: there's
        no server-side timer here, purging an unreachable node the instant
        it flips is allowed, Y (endpoint_purge_eligible_after_minutes) only
        affects how prominently axo-ui surfaces the action (see
        _purge_eligible_after_for/_decorate above).

        Delegates to purge_endpoint_use_case when configured -- it also
        cascades to every function this endpoint still owned (soft-deletes
        each, force-failing any of their still-queued/running jobs), since
        the endpoint can never come back to answer a FUNCTION_DELETE once
        it's gone. Falls back to the old Mongo-only behavior (no cascade,
        never touches Kurrent) when not wired, for callers that only need a
        minimal endpoints surface."""
        if purge_endpoint_use_case is not None:
            return purge_endpoint_use_case.execute(endpoint_id=endpoint_id)

        doc = endpoints.find_one({"_id": endpoint_id})
        if doc is None:
            raise HTTPException(status_code=404, detail="endpoint not found")
        if doc.get("status") not in ("stopped", "unreachable"):
            raise HTTPException(status_code=409, detail="endpoint must be stopped or unreachable before it can be purged")

        endpoints.delete_one({"_id": endpoint_id})
        purged = activity_repository.purge(endpoint_id=endpoint_id)
        return {"endpoint_id": endpoint_id, "purged_activity_count": purged}

    return router
