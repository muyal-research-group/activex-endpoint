from __future__ import annotations

import threading
import time

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
from axo_vem.application.projector.dispatcher import apply_event
from axo_vem.application.projector.handlers import ProjectorHandlers
from axo_vem.application.workspace.create_virtual_environment import CreateVirtualEnvironmentUseCase
from axo_vem.application.workspace.delete_virtual_environment import DeleteVirtualEnvironmentUseCase
from axo_vem.application.workspace.purge_virtual_environment import PurgeVirtualEnvironmentUseCase
from axo_vem.application.workspace.update_virtual_environment import UpdateVirtualEnvironmentUseCase
from axo_vem.config import Config
from axo_vem.infrastructure.auth.dependency import build_current_user_dependency, build_identity_dependency
from axo_vem.infrastructure.auth.xolo_client_factory import build_xolo_client
from axo_vem.infrastructure.container.endpoint_stats_poller import EndpointStatsPoller
from axo_vem.infrastructure.database.kurrent.appender import KurrentDBAppender
from axo_vem.infrastructure.database.kurrent.client import build_kurrent_client
from axo_vem.infrastructure.database.kurrent.subscriber import KurrentSubscriber
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository
from axo_vem.infrastructure.database.mongo.activity_retention_worker import ActivityRetentionWorker
from axo_vem.infrastructure.database.mongo.bucket_repository import (
    MongoBucketOwnerRepository,
    MongoBucketRepository,
    MongoDataItemRepository,
)
from axo_vem.infrastructure.database.mongo.choreography_repository import MongoChoreographyRepository
from axo_vem.infrastructure.database.mongo.choreography_run_repository import MongoChoreographyRunRepository
from axo_vem.infrastructure.database.mongo.checkpoint_store import MongoCheckpointStore
from axo_vem.infrastructure.database.mongo.client import build_mongo_database
from axo_vem.infrastructure.database.mongo.collections import ReadCollections
from axo_vem.infrastructure.database.mongo.consensus_repository import MongoConsensusRepository
from axo_vem.infrastructure.database.mongo.endpoint_repository import MongoEndpointRepository
from axo_vem.infrastructure.database.mongo.function_repository import MongoFunctionRepository
from axo_vem.infrastructure.database.mongo.job_repository import MongoJobRepository
from axo_vem.infrastructure.database.mongo.user_profile_repository import MongoUserProfileRepository
from axo_vem.infrastructure.database.mongo.virtual_environment_repository import (
    MongoVirtualEnvironmentRepository,
)
from axo_vem.infrastructure.resilience.errors import classify_kurrent_error, classify_mongo_error
from axo_vem.infrastructure.resilience.retry import retry_with_backoff
from axo_vem.infrastructure.transport.api.app import create_app
from axo_vem.infrastructure.transport.ws.broadcaster import Broadcaster
from axo_vem.infrastructure.transport.zmq_command.endpoint_liveness_worker import EndpointLivenessWorker
from axo_vem.infrastructure.transport.zmq_ingestion.router_server import IngestionRouterServer
from axo_vem.log import Log
from axo_vem.log.catalog import Component, Event
from axo_shared.container.spawner import ContainerSpawner
import uvicorn

class Server:
    """Hosts the ZMQ ingestion ROUTER (background thread), the Kurrent
    subscriber/projector (background thread), and FastAPI (main thread,
    blocking uvicorn.run) -- mirrors axo_endpoint/runner/server.py's
    RunnerServer combination pattern of one background-thread transport
    plus one blocking-on-main-thread HTTP server.

    Composition root for the domain/application/infrastructure split: reads
    config, builds real Mongo/Kurrent/Xolo clients, wraps them in concrete
    infrastructure repositories/adapters implementing the domain ABCs,
    injects those into application use cases, and attaches the use cases to
    the FastAPI/ZMQ adapters. Exercised only by the separate,
    container-backed integration suite, never by the fast unit tests.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._logger = Log(
            name                  = "axo-vem",
            log_level             = config.AXO_VEM_LOG_LEVEL,
            disabled              = config.AXO_VEM_LOG_DISABLED,
            to_file               = config.AXO_VEM_LOG_TO_FILE,
            path                  = config.AXO_VEM_LOG_PATH,
            filename              = config.AXO_VEM_LOG_FILENAME,
            output_path           = config.AXO_VEM_LOG_OUTPUT_PATH,
            error_output_path     = config.AXO_VEM_LOG_ERROR_OUTPUT_PATH,
            console_handler_level = config.AXO_VEM_LOG_CONSOLE_LEVEL,
            file_handler_level    = config.AXO_VEM_LOG_FILE_LEVEL,
            error_log             = config.AXO_VEM_LOG_ERROR_FILE,
            when                  = config.AXO_VEM_LOG_ROTATION_WHEN,
            interval              = config.AXO_VEM_LOG_ROTATION_INTERVAL,
            indent                = config.AXO_VEM_LOG_JSON_INDENT,
            use_rich              = config.AXO_VEM_LOG_USE_RICH,
            colorize              = config.AXO_VEM_LOG_COLORIZE,
        )

        db = build_mongo_database(config.AXO_VEM_MONGO_URI, config.AXO_VEM_MONGO_DB_NAME)
        self._wait_for_mongo(db)
        read_collections = ReadCollections(endpoints=db["endpoints"], functions=db["functions"], consensus=db["consensus"])

        activity_repository            = MongoActivityRepository(db["unified_activity"])
        user_profile_repository        = MongoUserProfileRepository(db["user_profiles"])
        virtual_environment_repository = MongoVirtualEnvironmentRepository(db["virtual_environments"])
        endpoint_repository            = MongoEndpointRepository(db["endpoints"])
        function_repository            = MongoFunctionRepository(db["functions"])
        consensus_repository           = MongoConsensusRepository(db["consensus"])
        job_repository                 = MongoJobRepository(db["jobs"])
        bucket_repository              = MongoBucketRepository(db["buckets"])
        data_item_repository           = MongoDataItemRepository(db["bucket_data"])
        bucket_owner_repository        = MongoBucketOwnerRepository(db["bucket_owners"])
        choreography_repository        = MongoChoreographyRepository(db["choreographies"])
        choreography_run_repository    = MongoChoreographyRunRepository(db["choreography_runs"])
        checkpoint_store               = MongoCheckpointStore(db["projector_checkpoints"])

        self._kurrent_client = build_kurrent_client(config.AXO_VEM_KURRENT_URI)
        self._wait_for_kurrent(self._kurrent_client)
        appender    = KurrentDBAppender(self._kurrent_client)
        broadcaster = Broadcaster()

        self._xolo_client = build_xolo_client(config)
        identity_dependency = build_identity_dependency(self._xolo_client, logger=self._logger)
        current_user_dependency = build_current_user_dependency(
            self._xolo_client, user_profile_repository, logger=self._logger,
        )

        signup_use_case                     = SignupUseCase(self._xolo_client, appender)
        create_profile_use_case             = CreateProfileUseCase(user_profile_repository, appender)
        update_profile_use_case             = UpdateProfileUseCase(user_profile_repository, appender)
        delete_profile_use_case             = DeleteProfileUseCase(user_profile_repository, appender)
        create_virtual_environment_use_case = CreateVirtualEnvironmentUseCase(appender)
        update_virtual_environment_use_case = UpdateVirtualEnvironmentUseCase(virtual_environment_repository, appender)
        delete_virtual_environment_use_case = DeleteVirtualEnvironmentUseCase(
            virtual_environment_repository, appender, read_collections.endpoints,
        )
        purge_virtual_environment_use_case = PurgeVirtualEnvironmentUseCase(
            db["virtual_environments"], activity_repository,
        )
        register_function_use_case = RegisterFunctionUseCase(
            virtual_environment_repository, endpoint_repository, config.AXO_VEM_ENDPOINT_COMMAND_TIMEOUT_SECONDS,
        )
        delete_function_use_case = DeleteFunctionUseCase(
            function_repository, endpoint_repository, job_repository, config.AXO_VEM_ENDPOINT_COMMAND_TIMEOUT_SECONDS,
        )
        update_function_use_case = UpdateFunctionUseCase(
            function_repository, endpoint_repository, config.AXO_VEM_ENDPOINT_COMMAND_TIMEOUT_SECONDS,
        )
        purge_function_version_use_case = PurgeFunctionVersionUseCase(
            db["functions"], activity_repository, appender,
        )
        submit_function_job_use_case = SubmitFunctionJobUseCase(
            function_repository, virtual_environment_repository, endpoint_repository,
            config.AXO_VEM_ENDPOINT_COMMAND_TIMEOUT_SECONDS,
        )
        purge_endpoint_use_case = PurgeEndpointUseCase(
            db["endpoints"], activity_repository, function_repository, job_repository, appender,
        )
        create_choreography_use_case = CreateChoreographyUseCase(appender)
        update_choreography_use_case = UpdateChoreographyUseCase(
            choreography_repository, choreography_run_repository, appender,
        )
        delete_choreography_use_case = DeleteChoreographyUseCase(
            choreography_repository, choreography_run_repository, appender,
        )
        purge_choreography_use_case = PurgeChoreographyUseCase(
            db["choreographies"], db["choreography_runs"], activity_repository,
        )
        run_choreography_use_case = RunChoreographyUseCase(
            choreography_repository=choreography_repository,
            run_repository=choreography_run_repository,
            function_repository=function_repository,
            endpoint_repository=endpoint_repository,
            data_item_repository=data_item_repository,
            submit_function_job_use_case=submit_function_job_use_case,
            broadcaster=broadcaster,
            command_timeout_seconds=config.AXO_VEM_ENDPOINT_COMMAND_TIMEOUT_SECONDS,
        )
        cancel_choreography_run_use_case = CancelChoreographyRunUseCase(
            choreography_repository=choreography_repository,
            run_repository=choreography_run_repository,
            run_use_case=run_choreography_use_case,
            command_timeout_seconds=config.AXO_VEM_ENDPOINT_COMMAND_TIMEOUT_SECONDS,
        )
        container_spawner             = ContainerSpawner()
        launch_endpoint_node_use_case = LaunchEndpointNodeUseCase(
            spawner             = container_spawner,
            image               = config.AXO_VEM_NODE_IMAGE,
            network             = config.AXO_VEM_NODE_NETWORK,
            mode                = config.AXO_VEM_DOCKER_MODE,
            endpoint_repository = endpoint_repository,
        )
        stop_endpoint_node_use_case = StopEndpointNodeUseCase(
            spawner = container_spawner, mode = config.AXO_VEM_DOCKER_MODE,
        )
        restart_endpoint_node_use_case = RestartEndpointNodeUseCase(
            spawner = container_spawner, mode = config.AXO_VEM_DOCKER_MODE,
        )
        self._stats_poller = EndpointStatsPoller(
            endpoints        = read_collections.endpoints,
            spawner          = container_spawner,
            mode             = config.AXO_VEM_DOCKER_MODE,
            broadcaster      = broadcaster,
            interval_seconds = config.AXO_VEM_STATS_POLL_INTERVAL_SECONDS,
            logger           = self._logger,
        )
        self._activity_retention_worker = ActivityRetentionWorker(
            activity_repository = activity_repository,
            retention_hours     = config.AXO_VEM_ACTIVITY_RETENTION_HOURS,
            tick_seconds        = config.AXO_VEM_ACTIVITY_RETENTION_TICK_SECONDS,
            logger              = self._logger,
        )
        self._endpoint_liveness_worker = EndpointLivenessWorker(
            endpoints            = read_collections.endpoints,
            event_publisher      = appender,
            stale_after_seconds  = config.AXO_VEM_ENDPOINT_STALE_AFTER_SECONDS,
            tick_seconds         = config.AXO_VEM_ENDPOINT_LIVENESS_TICK_SECONDS,
            ping_timeout_seconds = config.AXO_VEM_ENDPOINT_PING_TIMEOUT_SECONDS,
            logger               = self._logger,
        )

        self._ingestion = IngestionRouterServer(
            bind_address       = config.AXO_VEM_ROUTER_BIND,                   appender = appender, logger = self._logger,
            max_attempts       = config.AXO_VEM_DB_CONNECT_MAX_ATTEMPTS,
            base_delay_seconds = config.AXO_VEM_DB_CONNECT_BASE_DELAY_SECONDS,
            max_delay_seconds  = config.AXO_VEM_DB_CONNECT_MAX_DELAY_SECONDS,
        )

        projector_handlers = ProjectorHandlers(
            activity_recorder              = activity_repository,
            user_profile_repository        = user_profile_repository,
            virtual_environment_repository = virtual_environment_repository,
            endpoint_repository            = endpoint_repository,
            function_repository            = function_repository,
            consensus_recorder             = consensus_repository,
            job_repository                 = job_repository,
            bucket_repository              = bucket_repository,
            data_item_repository           = data_item_repository,
            choreography_repository        = choreography_repository,
        )
        self._subscriber = KurrentSubscriber(
            client=self._kurrent_client,
            checkpoint_store=checkpoint_store,
            on_event=lambda event_type, data: apply_event(
                projector_handlers, event_type, data, broadcaster, logger=self._logger, event_publisher=appender,
            ),
            logger=self._logger,
            max_attempts=config.AXO_VEM_DB_CONNECT_MAX_ATTEMPTS,
            base_delay_seconds=config.AXO_VEM_DB_CONNECT_BASE_DELAY_SECONDS,
            max_delay_seconds=config.AXO_VEM_DB_CONNECT_MAX_DELAY_SECONDS,
            stale_after_seconds=config.AXO_VEM_PROJECTOR_STALE_AFTER_SECONDS,
        )

        self._app = create_app(
            collections                          = read_collections,
            activity_repository                  = activity_repository,
            stream_admin                          = appender,
            user_profile_repository              = user_profile_repository,
            virtual_environment_repository        = virtual_environment_repository,
            job_repository                        = job_repository,
            bucket_repository                     = bucket_repository,
            data_item_repository                  = data_item_repository,
            bucket_owner_repository               = bucket_owner_repository,
            choreography_repository               = choreography_repository,
            choreography_run_repository           = choreography_run_repository,
            create_choreography_use_case          = create_choreography_use_case,
            update_choreography_use_case          = update_choreography_use_case,
            delete_choreography_use_case          = delete_choreography_use_case,
            purge_choreography_use_case           = purge_choreography_use_case,
            run_choreography_use_case             = run_choreography_use_case,
            cancel_choreography_run_use_case      = cancel_choreography_run_use_case,
            signup_use_case                       = signup_use_case,
            create_profile_use_case               = create_profile_use_case,
            update_profile_use_case               = update_profile_use_case,
            delete_profile_use_case               = delete_profile_use_case,
            create_virtual_environment_use_case   = create_virtual_environment_use_case,
            update_virtual_environment_use_case   = update_virtual_environment_use_case,
            delete_virtual_environment_use_case   = delete_virtual_environment_use_case,
            purge_virtual_environment_use_case    = purge_virtual_environment_use_case,
            register_function_use_case            = register_function_use_case,
            delete_function_use_case              = delete_function_use_case,
            update_function_use_case              = update_function_use_case,
            purge_function_version_use_case       = purge_function_version_use_case,
            submit_function_job_use_case          = submit_function_job_use_case,
            purge_endpoint_use_case               = purge_endpoint_use_case,
            endpoint_purge_eligible_after_minutes_default = config.AXO_VEM_ENDPOINT_PURGE_ELIGIBLE_AFTER_MINUTES,
            launch_endpoint_node_use_case          = launch_endpoint_node_use_case,
            node_api_uri                           = config.AXO_VEM_NODE_API_URI,
            stop_endpoint_node_use_case            = stop_endpoint_node_use_case,
            restart_endpoint_node_use_case         = restart_endpoint_node_use_case,
            kurrent_reader                        = self._kurrent_client,
            current_user_dependency               = current_user_dependency,
            identity_dependency                   = identity_dependency,
            xolo_client                           = self._xolo_client,
            endpoint_command_timeout_seconds      = config.AXO_VEM_ENDPOINT_COMMAND_TIMEOUT_SECONDS,
            cors_allow_origins                    = config.AXO_VEM_CORS_ORIGINS,
            broadcaster                           = broadcaster,
            logger                                = self._logger,
        )
        self._subscriber_thread: threading.Thread | None = None
        self._stats_poller_thread: threading.Thread | None = None
        self._activity_retention_thread: threading.Thread | None = None
        self._endpoint_liveness_thread: threading.Thread | None = None

    def _wait_for_mongo(self, db) -> None:
        """Eager, retry-guarded connectivity probe -- closes the startup
        race where MongoDB isn't accepting connections yet when this
        process starts. Both MongoClient and KurrentDBClient are lazy (no
        network I/O until first use), so without this the first real
        failure would surface much later, inside whichever background
        thread happens to touch the database first."""
        config = self._config

        def on_attempt_failed(attempt: int, exc: Exception) -> None:
            error_code, description = classify_mongo_error(exc)
            self._logger.warning_event(
                Event.Mongo.CONNECT_FAILED,
                component=Component.MONGO,
                attempt=attempt,
                max_attempts=config.AXO_VEM_DB_CONNECT_MAX_ATTEMPTS,
                error_code=error_code,
                description=description,
            )

        t0 = time.monotonic()
        retry_with_backoff(
            lambda: db.command("ping"),
            max_attempts=config.AXO_VEM_DB_CONNECT_MAX_ATTEMPTS,
            base_delay_seconds=config.AXO_VEM_DB_CONNECT_BASE_DELAY_SECONDS,
            max_delay_seconds=config.AXO_VEM_DB_CONNECT_MAX_DELAY_SECONDS,
            on_attempt_failed=on_attempt_failed,
        )
        self._logger.info_event(
            Event.Mongo.CONNECTED,
            component=Component.MONGO,
            db_name=config.AXO_VEM_MONGO_DB_NAME,
            duration_ms=round((time.monotonic() - t0) * 1000, 2),
        )

    def _wait_for_kurrent(self, client) -> None:
        """Same eager retry-guarded probe as _wait_for_mongo, for
        KurrentDB -- this is what actually closes the race that killed
        both KurrentSubscriber and IngestionRouterServer at startup."""
        config = self._config

        def on_attempt_failed(attempt: int, exc: Exception) -> None:
            error_code, description = classify_kurrent_error(exc)
            self._logger.warning_event(
                Event.Kurrent.CONNECT_FAILED,
                component=Component.KURRENT,
                attempt=attempt,
                max_attempts=config.AXO_VEM_DB_CONNECT_MAX_ATTEMPTS,
                error_code=error_code,
                description=description,
            )

        def probe() -> None:
            list(client.read_all(backwards=True, limit=1))

        t0 = time.monotonic()
        retry_with_backoff(
            probe,
            max_attempts=config.AXO_VEM_DB_CONNECT_MAX_ATTEMPTS,
            base_delay_seconds=config.AXO_VEM_DB_CONNECT_BASE_DELAY_SECONDS,
            max_delay_seconds=config.AXO_VEM_DB_CONNECT_MAX_DELAY_SECONDS,
            on_attempt_failed=on_attempt_failed,
        )
        self._logger.info_event(
            Event.Kurrent.CONNECTED,
            component=Component.KURRENT,
            duration_ms=round((time.monotonic() - t0) * 1000, 2),
        )

    def start(self) -> None:
        """Starts the ingestion ROUTER and Kurrent subscriber threads, then
        blocks running FastAPI on the calling (main) thread."""

        self._ingestion.start()
        self._subscriber_thread = threading.Thread(target=self._subscriber.run_forever, daemon=True)
        self._subscriber_thread.start()
        self._stats_poller_thread = threading.Thread(target=self._stats_poller.run_forever, daemon=True)
        self._stats_poller_thread.start()
        self._activity_retention_thread = threading.Thread(
            target=self._activity_retention_worker.run_forever, daemon=True,
        )
        self._activity_retention_thread.start()
        self._endpoint_liveness_thread = threading.Thread(
            target=self._endpoint_liveness_worker.run_forever, daemon=True,
        )
        self._endpoint_liveness_thread.start()

        self._logger.info_event(
            Event.Server.STARTED,
            component=Component.SERVER,
            router_bind=self._config.AXO_VEM_ROUTER_BIND,
            http_host=self._config.AXO_VEM_HTTP_HOST,
            http_port=self._config.AXO_VEM_HTTP_PORT,
        )

        uvicorn_config = uvicorn.Config(
            self._app,
            host      = self._config.AXO_VEM_HTTP_HOST,
            port      = self._config.AXO_VEM_HTTP_PORT,
            log_level = "warning",
        )
        uvicorn.Server(uvicorn_config).run()

    def stop(self) -> None:
        """Stops the ingestion ROUTER and signals the Kurrent subscriber,
        stats poller, and activity retention worker to stop at their next
        loop iteration (FastAPI itself stops when start()'s
        uvicorn.Server.run() returns, e.g. on SIGINT/SIGTERM)."""
        self._ingestion.stop()
        self._subscriber.stop()
        self._stats_poller.stop()
        self._activity_retention_worker.stop()
        self._endpoint_liveness_worker.stop()
        self._logger.info_event(Event.Server.STOPPED, component=Component.SERVER)
