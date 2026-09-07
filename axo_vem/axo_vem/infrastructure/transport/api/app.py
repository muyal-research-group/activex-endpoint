from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, List, Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from xolo.client import XoloClient
from xolo.client.models import UserDTO

from axo_vem.application.choreography.cancel_choreography_run import CancelChoreographyRunUseCase
from axo_vem.application.choreography.create_choreography import CreateChoreographyUseCase
from axo_vem.application.choreography.delete_choreography import DeleteChoreographyUseCase
from axo_vem.application.choreography.purge_choreography import PurgeChoreographyUseCase
from axo_vem.application.choreography.run_choreography import RunChoreographyUseCase
from axo_vem.application.choreography.update_choreography import UpdateChoreographyUseCase
from axo_vem.application.compute.delete_function import DeleteFunctionUseCase
from axo_vem.application.compute.purge_function_version import PurgeFunctionVersionUseCase
from axo_vem.application.compute.register_function import RegisterFunctionUseCase
from axo_vem.application.compute.submit_function_job import SubmitFunctionJobUseCase
from axo_vem.application.compute.update_function import UpdateFunctionUseCase
from axo_vem.application.identity.create_profile import CreateProfileUseCase
from axo_vem.application.identity.delete_profile import DeleteProfileUseCase
from axo_vem.application.identity.signup import SignupUseCase
from axo_vem.application.identity.update_profile import UpdateProfileUseCase
from axo_vem.application.nodes.launch_endpoint_node import LaunchEndpointNodeUseCase
from axo_vem.application.nodes.purge_endpoint import PurgeEndpointUseCase
from axo_vem.application.nodes.restart_endpoint_node import RestartEndpointNodeUseCase
from axo_vem.application.nodes.stop_endpoint_node import StopEndpointNodeUseCase
from axo_vem.application.workspace.create_virtual_environment import CreateVirtualEnvironmentUseCase
from axo_vem.application.workspace.delete_virtual_environment import DeleteVirtualEnvironmentUseCase
from axo_vem.application.workspace.purge_virtual_environment import PurgeVirtualEnvironmentUseCase
from axo_vem.application.workspace.update_virtual_environment import UpdateVirtualEnvironmentUseCase
from axo_vem.domain.choreography.repository import ChoreographyRepository
from axo_vem.domain.choreography.run_repository import ChoreographyRunRepository
from axo_vem.domain.data.repository import BucketOwnerRepository, BucketRepository, DataItemRepository
from axo_vem.domain.events.stream_admin import StreamAdmin
from axo_vem.domain.execution.repository import JobRepository
from axo_vem.domain.identity.repository import UserProfileRepository
from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository
from axo_vem.infrastructure.database.kurrent.reader import KurrentReader
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository
from axo_vem.infrastructure.database.mongo.collections import ReadCollections
from axo_vem.infrastructure.transport.api.controllers import buckets as buckets_routes
from axo_vem.infrastructure.transport.api.controllers import choreographies as choreographies_routes
from axo_vem.infrastructure.transport.api.controllers import consensus as consensus_routes
from axo_vem.infrastructure.transport.api.controllers import endpoints as endpoints_routes
from axo_vem.infrastructure.transport.api.controllers import events as events_routes
from axo_vem.infrastructure.transport.api.controllers import functions as functions_routes
from axo_vem.infrastructure.transport.api.controllers import history as history_routes
from axo_vem.infrastructure.transport.api.controllers import jobs as jobs_routes
from axo_vem.infrastructure.transport.api.controllers import user_profile as user_profile_routes
from axo_vem.infrastructure.transport.api.controllers import virtual_environments as virtual_environments_routes
from axo_vem.infrastructure.transport.api.controllers import websockets as websockets_routes
from axo_vem.infrastructure.transport.api.errors import register_exception_handlers
from axo_vem.infrastructure.transport.api.logging_middleware import register_logging_middleware
from axo_vem.infrastructure.transport.ws.broadcaster import Broadcaster
from axo_vem.log import DumbLogger, Log

OPENAPI_TAGS = [
    {
        "name": "user profile",
        "description": "Operations for Xolo authentication client sessions, user signups, and preference configurations.",
    },
    {
        "name": "virtual environment",
        "description": "Logical multi tenant workspaces, namespace boundaries, and cluster topology routing.",
    },
    {
        "name": "endpoint management",
        "description": "Physical infrastructure compute nodes, environment assignments, and operational status records.",
    },
    {
        "name": "function registries",
        "description": "Function code registrations, compilation specs, and deployment runtime targets.",
    },
    {
        "name": "active objects",
        "description": "Lifecycle monitoring, state transitions, and mailbox processing for concurrent execution actors.",
    },
    {
        "name": "job telemetry",
        "description": "Historical execution pipelines, queue metrics, and structured error logs sourced from KurrentDB.",
    },
]


def _auth_not_configured(*args, **kwargs):
    """Fallback used in place of a real current_user_dependency when none
    was supplied to create_app -- fails closed (401) rather than either
    crashing at app-construction time (Depends(None) has no signature for
    FastAPI to introspect) or silently leaving cluster-observability routes
    open. Only reachable in a deployment that never built a real Xolo-backed
    dependency; server.py always does."""
    raise HTTPException(status_code=401, detail="authentication is not configured on this deployment")


def create_app(
    collections: ReadCollections,
    activity_repository: MongoActivityRepository,
    stream_admin: Optional[StreamAdmin] = None,
    user_profile_repository: Optional[UserProfileRepository] = None,
    virtual_environment_repository: Optional[VirtualEnvironmentRepository] = None,
    job_repository: Optional[JobRepository] = None,
    bucket_repository: Optional[BucketRepository] = None,
    data_item_repository: Optional[DataItemRepository] = None,
    bucket_owner_repository: Optional[BucketOwnerRepository] = None,
    choreography_repository: Optional[ChoreographyRepository] = None,
    choreography_run_repository: Optional[ChoreographyRunRepository] = None,
    create_choreography_use_case: Optional[CreateChoreographyUseCase] = None,
    update_choreography_use_case: Optional[UpdateChoreographyUseCase] = None,
    delete_choreography_use_case: Optional[DeleteChoreographyUseCase] = None,
    purge_choreography_use_case: Optional[PurgeChoreographyUseCase] = None,
    run_choreography_use_case: Optional[RunChoreographyUseCase] = None,
    cancel_choreography_run_use_case: Optional[CancelChoreographyRunUseCase] = None,
    signup_use_case: Optional[SignupUseCase] = None,
    create_profile_use_case: Optional[CreateProfileUseCase] = None,
    update_profile_use_case: Optional[UpdateProfileUseCase] = None,
    delete_profile_use_case: Optional[DeleteProfileUseCase] = None,
    create_virtual_environment_use_case: Optional[CreateVirtualEnvironmentUseCase] = None,
    update_virtual_environment_use_case: Optional[UpdateVirtualEnvironmentUseCase] = None,
    delete_virtual_environment_use_case: Optional[DeleteVirtualEnvironmentUseCase] = None,
    purge_virtual_environment_use_case: Optional[PurgeVirtualEnvironmentUseCase] = None,
    register_function_use_case: Optional[RegisterFunctionUseCase] = None,
    delete_function_use_case: Optional[DeleteFunctionUseCase] = None,
    update_function_use_case: Optional[UpdateFunctionUseCase] = None,
    purge_function_version_use_case: Optional[PurgeFunctionVersionUseCase] = None,
    submit_function_job_use_case: Optional[SubmitFunctionJobUseCase] = None,
    purge_endpoint_use_case: Optional[PurgeEndpointUseCase] = None,
    endpoint_purge_eligible_after_minutes_default: int = 60,
    launch_endpoint_node_use_case: Optional[LaunchEndpointNodeUseCase] = None,
    node_api_uri: Optional[str] = None,
    stop_endpoint_node_use_case: Optional[StopEndpointNodeUseCase] = None,
    restart_endpoint_node_use_case: Optional[RestartEndpointNodeUseCase] = None,
    kurrent_reader: Optional[KurrentReader] = None,
    current_user_dependency: Optional[Callable[..., UserDTO]] = None,
    identity_dependency: Optional[Callable[..., UserDTO]] = None,
    xolo_client: Optional[XoloClient] = None,
    endpoint_command_timeout_seconds: float = 3.0,
    cors_allow_origins: Optional[List[str]] = None,
    broadcaster: Optional[Broadcaster] = None,
    logger: Optional[Union[Log, DumbLogger]] = None,
) -> FastAPI:
    """Builds the external HTTP surface. Every route is authenticated via
    current_user_dependency (infrastructure.auth.dependency.get_current_user)
    except POST /login and POST /signup (necessarily public -- that's how a
    caller obtains credentials in the first place) and POST /profile (uses
    the lighter identity_dependency, since it must work before a local
    UserProfile exists yet -- see infrastructure/transport/api/controllers/user_profile.py).

    Domain errors raised by application use cases (NotFoundError/
    NotOwnerError/ConflictError/DomainError) are translated to HTTP status
    codes by the handlers registered in infrastructure/transport/api/errors.py.
    """
    lifespan = None
    if broadcaster is not None:
        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            # The only point in the process lifecycle guaranteed to be
            # running on the same loop uvicorn actually serves WebSocket
            # connections on -- see Broadcaster.bind_loop's docstring.
            broadcaster.bind_loop(asyncio.get_running_loop())
            yield

    app = FastAPI(
        title="axo-vem",
        openapi_tags=OPENAPI_TAGS,
        swagger_ui_parameters={"docExpansion": "none"},
        lifespan=lifespan,
    )
    _logger: Union[Log, DumbLogger] = logger or DumbLogger()
    register_exception_handlers(app, logger=_logger)
    register_logging_middleware(app, logger=_logger)

    if broadcaster is not None:
        app.include_router(websockets_routes.build_router(broadcaster))

    if cors_allow_origins:
        # allow_credentials=False -- sessions are two manually-attached
        # headers (Authorization/Temporal-Secret-Key), never browser-managed
        # cookies, so there's nothing here that needs credentialed CORS.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_allow_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    required_auth_dependency = current_user_dependency or _auth_not_configured

    app.include_router(endpoints_routes.build_router(
        collections.endpoints, required_auth_dependency, activity_repository, endpoint_command_timeout_seconds,
        launch_endpoint_node_use_case, node_api_uri,
        stop_endpoint_node_use_case, restart_endpoint_node_use_case,
        user_profile_repository, endpoint_purge_eligible_after_minutes_default,
        purge_endpoint_use_case=purge_endpoint_use_case,
    ))
    if (
        register_function_use_case is not None
        and delete_function_use_case is not None
        and update_function_use_case is not None
        and purge_function_version_use_case is not None
    ):
        app.include_router(functions_routes.build_router(
            collections.functions, required_auth_dependency,
            register_function_use_case, delete_function_use_case,
            update_function_use_case, purge_function_version_use_case,
        ))
    app.include_router(consensus_routes.build_router(collections.consensus, required_auth_dependency))
    app.include_router(history_routes.build_router(
        activity_repository, virtual_environment_repository, required_auth_dependency, user_profile_repository,
    ))
    if kurrent_reader is not None:
        app.include_router(events_routes.build_router(kurrent_reader, required_auth_dependency))
    if job_repository is not None:
        app.include_router(jobs_routes.build_router(
            job_repository, required_auth_dependency, collections.endpoints, endpoint_command_timeout_seconds,
            submit_function_job_use_case,
        ))
    if bucket_repository is not None and data_item_repository is not None and bucket_owner_repository is not None:
        app.include_router(buckets_routes.build_router(
            bucket_repository, data_item_repository, bucket_owner_repository,
            collections.endpoints, collections.consensus,
            required_auth_dependency, endpoint_command_timeout_seconds,
        ))
    if (
        user_profile_repository is not None
        and signup_use_case is not None
        and create_profile_use_case is not None
        and update_profile_use_case is not None
        and delete_profile_use_case is not None
        and current_user_dependency is not None
        and identity_dependency is not None
        and xolo_client is not None
    ):
        app.include_router(user_profile_routes.build_router(
            user_profile_repository, signup_use_case, create_profile_use_case,
            update_profile_use_case, delete_profile_use_case,
            current_user_dependency, identity_dependency, xolo_client,
        ))
    if (
        virtual_environment_repository is not None
        and create_virtual_environment_use_case is not None
        and update_virtual_environment_use_case is not None
        and delete_virtual_environment_use_case is not None
        and purge_virtual_environment_use_case is not None
        and current_user_dependency is not None
    ):
        app.include_router(virtual_environments_routes.build_router(
            virtual_environment_repository, create_virtual_environment_use_case,
            update_virtual_environment_use_case, delete_virtual_environment_use_case,
            purge_virtual_environment_use_case,
            current_user_dependency,
        ))
    if (
        choreography_repository is not None
        and choreography_run_repository is not None
        and create_choreography_use_case is not None
        and update_choreography_use_case is not None
        and delete_choreography_use_case is not None
        and purge_choreography_use_case is not None
        and current_user_dependency is not None
    ):
        app.include_router(choreographies_routes.build_router(
            choreography_repository, choreography_run_repository, create_choreography_use_case,
            update_choreography_use_case, delete_choreography_use_case, purge_choreography_use_case,
            current_user_dependency,
            run_use_case=run_choreography_use_case,
            cancel_run_use_case=cancel_choreography_run_use_case,
        ))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
