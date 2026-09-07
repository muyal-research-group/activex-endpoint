from __future__ import annotations

import threading
import time
from typing import Callable, Dict, FrozenSet, List, Optional, Set

import zmq
from option import Err, Ok, Result

from axo_endpoint.core.consensus import (
    BucketRegistrySyncBridge,
    BullyLeaderElector,
    ClusterMember,
    ConcurrencyLedger,
    ContainerCountEntry,
    DataRegistrySyncBridge,
    DirtyTracker,
    InMemoryReplicatedStateMachine,
    LeaderView,
    RegistrySyncBridge,
    ResultConsistencySweeper,
    ResultConsistencyStore,
    decode_cluster_state,
    encode_state_changes,
)
from axo_endpoint.core.activity import ActivityTrackingBridge
from axo_endpoint.core.external import ExternalEventForwardingBridge
from axo_shared.activity.models import (
    CONTAINER_CRASHED_EVENT,
    CONTAINER_DISMISSED_EVENT,
    CONTAINER_READY_EVENT,
    CONTAINER_SPAWNED_EVENT,
    FUNCTION_BUILD_COMPLETED_EVENT,
    FUNCTION_BUILD_FAILED_EVENT,
    FUNCTION_BUILD_STARTED_EVENT,
    FUNCTION_CRASHED_EVENT,
    FUNCTION_DELETED_EVENT,
    FUNCTION_DELETE_FAILED_EVENT,
    FUNCTION_DEPLOYED_EVENT,
    FUNCTION_DEPLOY_FAILED_EVENT,
    FUNCTION_STOPPED_EVENT,
    FUNCTION_REGISTER_FAILED_EVENT,
    FUNCTION_REPLICATED_EVENT,
    FUNCTION_UPDATED_EVENT,
    JOB_STARTED_EVENT,
)
from axo_shared.activity.repository import InMemoryRepository
from axo_shared.events import models as event_models
from axo_endpoint.core.consensus.state_machine import StateMutation
from axo_endpoint.core.data import (
    BUCKET_REGISTERED_EVENT,
    DATA_DELETED_EVENT,
    DATA_REGISTERED_EVENT,
    DATA_UPLOAD_COMPLETED_EVENT,
    BucketRegistry,
    DataRegistry,
)
from axo_endpoint.core.errors import AxoError
from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.functions.lifecycle import FunctionState
from axo_endpoint.core.network import PeerInfo
from axo_endpoint.core.results import FunctionResult
from axo_shared.protocol import Command, CommandResult
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend
from axo_endpoint.dispatch import InMemoryCommandDispatcher
from axo_endpoint.log import Log
from axo_endpoint.log.catalog import Component, Event
from axo_endpoint.config import Config
from axo_endpoint.service.blob_replication import BlobReplicator
from axo_endpoint.service.consensus_loop import (
    CLUSTER_DEGRADED_EVENT,
    CLUSTER_QUORUM_LOST_EVENT,
    CLUSTER_QUORUM_RESTORED_EVENT,
    CONSENSUS_VIEW_CHANGED_EVENT,
    LEADER_ELECTED_EVENT,
    run_consensus_tick,
)
from axo_endpoint.service.container import ContainerResultReceiver, ContainerSummoner
from axo_endpoint.service.container.handle import ContainerStatus
from axo_endpoint.service.handlers import (
    ActivityListHandler,
    BucketRegisterHandler,
    ConcurrencyReconcilePullHandler,
    ConcurrencySlotReleaseHandler,
    ConcurrencySlotRequestHandler,
    ConsistencyCheckRequestHandler,
    ContainerBootstrapHandler,
    DataChunkGetHandler,
    DataChunkPutHandler,
    DataDeleteHandler,
    DataInfoHandler,
    DataRegisterHandler,
    DataStatusHandler,
    FunctionDeleteHandler,
    FunctionRegisterHandler,
    FunctionUpdateHandler,
    JobCancelHandler,
    JobForwardHandler,
    JobResultHandler,
    JobResultReplicateHandler,
    JobResultSyncHandler,
    JobSubmitHandler,
    LeaderProxyHandler,
    MetricsHandler,
    PeerAnnounceHandler,
    PingHandler,
    StateSyncPullHandler,
    StateSyncPushHandler,
    VirtualEnvAssignHandler,
    build_completion_recorder,
    make_replicate_fn,
    make_reverify_fn,
)
from axo_endpoint.service.runtime.concurrency_client import ConcurrencyClient
from axo_endpoint.service.runtime.container_runtime import ContainerFunctionRuntime
from axo_endpoint.service.runtime.dispatcher import RuntimeDispatcher
from axo_endpoint.service.runtime.process_runtime import ProcessFunctionRuntime
from axo_endpoint.service.runtime.scratch import sweep_orphaned_scratch_dirs
from axo_shared import wire
from axo_endpoint.service.transport.address import resolve_peer_address
from axo_endpoint.service.transport.event_publisher import ZmqEventPublisher
from axo_endpoint.service.transport.heartbeat_zmq import (
    ZmqHeartbeatPublisher,
    ZmqHeartbeatSubscriber,
    run_heartbeat_gc,
)
from axo_endpoint.service.transport.router_server import RouterServer
from axo_shared.wire import WireError


class App:
    """Builds and runs one complete endpoint: storage, the function registry,
    the job queue, the process runtime, and the network transport, all
    connected together."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._logger = Log(
            name                  = "axo-endpoint",
            context               = {"endpoint_id": config.AXO_ENDPOINT_ID},
            log_level             = config.AXO_ENDPOINT_LOG_LEVEL,
            disabled              = config.AXO_ENDPOINT_LOG_DISABLED,
            to_file               = config.AXO_ENDPOINT_LOG_TO_FILE,
            path                  = config.AXO_ENDPOINT_LOG_PATH,
            filename              = config.AXO_ENDPOINT_LOG_FILENAME,
            output_path           = config.AXO_ENDPOINT_LOG_OUTPUT_PATH,
            error_output_path     = config.AXO_ENDPOINT_LOG_ERROR_OUTPUT_PATH,
            console_handler_level = config.AXO_ENDPOINT_LOG_CONSOLE_LEVEL,
            file_handler_level    = config.AXO_ENDPOINT_LOG_FILE_LEVEL,
            error_log             = config.AXO_ENDPOINT_LOG_ERROR_FILE,
            when                  = config.AXO_ENDPOINT_LOG_ROTATION_WHEN,
            interval              = config.AXO_ENDPOINT_LOG_ROTATION_INTERVAL,
            indent                = config.AXO_ENDPOINT_LOG_JSON_INDENT,
            use_rich              = config.AXO_ENDPOINT_LOG_USE_RICH,
            colorize              = config.AXO_ENDPOINT_LOG_COLORIZE,
        )

        self.functions_store = InMemoryStorageBackend()
        self.results_store   = InMemoryStorageBackend()
        self.event_bus       = InMemoryEventBus()
        self.storage_backends = {
            "fs": FilesystemStorageBackend(root=config.AXO_ENDPOINT_DATAIO_FS_ROOT),
        }
        self.registry        = FunctionRegistry(backend=self.functions_store, event_bus=self.event_bus)
        self.data_store      = InMemoryStorageBackend()
        self.data_registry   = DataRegistry(
            catalog=self.data_store, blob_backends=self.storage_backends, event_bus=self.event_bus,
        )
        self.bucket_store    = InMemoryStorageBackend()
        self.bucket_registry = BucketRegistry(catalog=self.bucket_store, event_bus=self.event_bus)

        self.elector               = BullyLeaderElector(self_id=config.AXO_ENDPOINT_ID)
        self.dirty_tracker         = DirtyTracker(
            max_dirty_count=config.AXO_ENDPOINT_CONSENSUS_REPLICATION_MAX_DIRTY
        )
        # Cluster-wide max_concurrency: leader-owned slot ledger, and the
        # per-job_id "is every endpoint's copy of this result the same"
        # bookkeeping for result replication -- neither has any dependency
        # on heartbeat/elector wiring, so both can be built this early.
        self.concurrency_ledger      = ConcurrencyLedger(strategy=config.AXO_ENDPOINT_LOAD_BALANCE_STRATEGY)
        self.result_consistency_store = ResultConsistencyStore()
        self.cluster_state_machine = InMemoryReplicatedStateMachine()
        self.registry_sync         = RegistrySyncBridge(
            registry=self.registry, backend=self.functions_store, dirty_tracker=self.dirty_tracker,
            event_bus=self.event_bus,
        )
        self.event_bus.subscribe(FunctionState.REGISTERED.value, self.registry_sync.on_function_event)
        self.event_bus.subscribe(FUNCTION_UPDATED_EVENT, self.registry_sync.on_function_updated)
        self.event_bus.subscribe(FUNCTION_DELETED_EVENT, self.registry_sync.on_function_deleted)
        self.data_registry_sync    = DataRegistrySyncBridge(
            registry=self.data_registry, catalog=self.data_store, dirty_tracker=self.dirty_tracker,
        )
        self.event_bus.subscribe(DATA_REGISTERED_EVENT, self.data_registry_sync.on_data_event)
        self.event_bus.subscribe(DATA_DELETED_EVENT, self.data_registry_sync.on_data_deleted)
        self.bucket_registry_sync  = BucketRegistrySyncBridge(
            registry=self.bucket_registry, catalog=self.bucket_store, dirty_tracker=self.dirty_tracker,
        )
        self.event_bus.subscribe(BUCKET_REGISTERED_EVENT, self.bucket_registry_sync.on_bucket_event)
        self.blob_replicator       = BlobReplicator(
            data_registry=self.data_registry,
            storage_backends=self.storage_backends,
            chunk_bytes=config.AXO_ENDPOINT_CONSENSUS_BLOB_CHUNK_BYTES,
            rate_limit_bytes_per_second=config.AXO_ENDPOINT_CONSENSUS_BLOB_RATE_LIMIT_BYTES_PER_SECOND,
            enabled_kinds=config.AXO_ENDPOINT_BLOB_REPLICATION_ENABLED_KINDS,
            recheck_seconds=config.AXO_ENDPOINT_BLOB_REPLICATION_RECHECK_SECONDS,
            logger=self._logger,
        )

        self.activity_repository = InMemoryRepository(
            max_entries=config.AXO_ENDPOINT_ACTIVITY_LOG_MAX_ENTRIES
        )
        self.activity_bridge = ActivityTrackingBridge(
            repository=self.activity_repository, results=self.results_store,
        )
        self.event_bus.subscribe("JOB_SUBMITTED", self.activity_bridge.on_job_submitted)
        self.event_bus.subscribe("JOB_COMPLETED", self.activity_bridge.on_job_finished)
        self.event_bus.subscribe("JOB_FAILED", self.activity_bridge.on_job_finished)
        self.event_bus.subscribe(CONTAINER_SPAWNED_EVENT, self.activity_bridge.on_container_event)
        self.event_bus.subscribe(CONTAINER_READY_EVENT, self.activity_bridge.on_container_event)
        self.event_bus.subscribe(CONTAINER_CRASHED_EVENT, self.activity_bridge.on_container_event)
        self.event_bus.subscribe(CONTAINER_DISMISSED_EVENT, self.activity_bridge.on_container_event)

        # External API publishing -- entirely gated by AXO_ENDPOINT_API_URI.
        # Unset: no publisher, no bridge, no subscriptions -- zero new behavior.
        self.external_publisher: Optional[ZmqEventPublisher] = None
        self.external_bridge: Optional[ExternalEventForwardingBridge] = None
        if config.AXO_ENDPOINT_API_URI:
            self.external_publisher = ZmqEventPublisher(
                api_uri=config.AXO_ENDPOINT_API_URI,
                endpoint_id=config.AXO_ENDPOINT_ID,
                logger=self._logger,
            )
            self.external_bridge = ExternalEventForwardingBridge(
                publisher=self.external_publisher,
                endpoint_id=config.AXO_ENDPOINT_ID,
                results=self.results_store,
                function_registry=self.registry,
                get_virtual_environment_id=self._get_virtual_environment_id,
                logger=self._logger,
            )
            # Only REGISTERED ever actually fires via FunctionRegistry.register() --
            # the other FunctionState values are only reachable through
            # FunctionRegistry.transition(), which nothing in this codebase calls.
            self.event_bus.subscribe(FunctionState.REGISTERED.value, self.external_bridge.on_function_event)
            self.event_bus.subscribe(FUNCTION_REPLICATED_EVENT, self.external_bridge.on_function_event)
            self.event_bus.subscribe(FUNCTION_REGISTER_FAILED_EVENT, self.external_bridge.on_function_register_failed)
            self.event_bus.subscribe(FUNCTION_DEPLOYED_EVENT, self.external_bridge.on_function_deployed)
            self.event_bus.subscribe(CONTAINER_SPAWNED_EVENT, self.external_bridge.on_function_deployed)
            self.event_bus.subscribe(CONTAINER_READY_EVENT, self.external_bridge.on_function_deployed)
            self.event_bus.subscribe(FUNCTION_DEPLOY_FAILED_EVENT, self.external_bridge.on_function_deploy_failed)
            self.event_bus.subscribe(CONTAINER_CRASHED_EVENT, self.external_bridge.on_function_deploy_failed)
            self.event_bus.subscribe(FUNCTION_UPDATED_EVENT, self.external_bridge.on_function_updated)
            self.event_bus.subscribe(FUNCTION_STOPPED_EVENT, self.external_bridge.on_function_stopped)
            self.event_bus.subscribe(FUNCTION_CRASHED_EVENT, self.external_bridge.on_function_crashed)
            self.event_bus.subscribe(FUNCTION_BUILD_STARTED_EVENT, self.external_bridge.on_function_build_event)
            self.event_bus.subscribe(FUNCTION_BUILD_COMPLETED_EVENT, self.external_bridge.on_function_build_event)
            self.event_bus.subscribe(FUNCTION_BUILD_FAILED_EVENT, self.external_bridge.on_function_build_event)
            self.event_bus.subscribe(FUNCTION_DELETED_EVENT, self.external_bridge.on_function_deleted)
            self.event_bus.subscribe(FUNCTION_DELETE_FAILED_EVENT, self.external_bridge.on_function_delete_failed)
            self.event_bus.subscribe("JOB_SUBMITTED", self.external_bridge.on_job_queued)
            self.event_bus.subscribe(JOB_STARTED_EVENT, self.external_bridge.on_job_started)
            self.event_bus.subscribe("JOB_COMPLETED", self.external_bridge.on_job_finished)
            self.event_bus.subscribe("JOB_FAILED", self.external_bridge.on_job_finished)
            self.event_bus.subscribe(BUCKET_REGISTERED_EVENT, self.external_bridge.on_bucket_registered)
            self.event_bus.subscribe(DATA_REGISTERED_EVENT, self.external_bridge.on_data_registered)
            self.event_bus.subscribe(DATA_UPLOAD_COMPLETED_EVENT, self.external_bridge.on_data_upload_completed)
            self.event_bus.subscribe(DATA_DELETED_EVENT, self.external_bridge.on_data_deleted)
            self.event_bus.subscribe(LEADER_ELECTED_EVENT, self.external_bridge.on_leader_elected)
            self.event_bus.subscribe(CONSENSUS_VIEW_CHANGED_EVENT, self.external_bridge.on_consensus_view_changed)
            self.event_bus.subscribe(CLUSTER_QUORUM_LOST_EVENT, self.external_bridge.on_cluster_quorum_event)
            self.event_bus.subscribe(CLUSTER_QUORUM_RESTORED_EVENT, self.external_bridge.on_cluster_quorum_event)
            self.event_bus.subscribe(CLUSTER_DEGRADED_EVENT, self.external_bridge.on_cluster_quorum_event)

        self.dispatcher = InMemoryCommandDispatcher(
            max_queue_size = config.AXO_ENDPOINT_QUEUE_MAX_DEPTH,
            worker_count   = config.AXO_ENDPOINT_QUEUE_WORKERS,
            logger         = self._logger,
        )

        # Result replication (executor -> leader -> every endpoint) is wired
        # in below, once heartbeat/leader-proxy collaborators exist -- but
        # on_complete (built here, well before that) is a plain closure, not
        # an object with an attach_*() method, so this mutable indirection
        # is what lets it start replicating once the real function is ready,
        # the same way PEER_ANNOUNCE/VIRTUAL_ENV_ASSIGN mutate direct_handlers
        # post-hoc instead of needing everything built up front.
        self._replicate_result_fn: Optional[Callable[[FunctionResult], None]] = None

        def _replicate_result(result: FunctionResult) -> None:
            if self._replicate_result_fn is not None:
                self._replicate_result_fn(result)

        on_complete = build_completion_recorder(
            results       = self.results_store,
            event_bus     = self.event_bus,
            data_registry = self.data_registry,
            logger        = self._logger,
            replicate_fn  = _replicate_result,
        )
        self.process_runtime = ProcessFunctionRuntime(
            function_registry  = self.registry,
            on_complete        = on_complete,
            scratch_root       = config.AXO_ENDPOINT_SCRATCH_ROOT,
            memory_limit_bytes = config.AXO_ENDPOINT_WORKER_RLIMIT_AS_BYTES,
            cpu_limit_seconds  = config.AXO_ENDPOINT_WORKER_RLIMIT_CPU_SECONDS,
            storage_backends   = self.storage_backends,
            data_registry      = self.data_registry,
            event_bus          = self.event_bus,
            logger             = self._logger,
        )
        self.container_summoner = ContainerSummoner(config=config, event_bus=self.event_bus, logger=self._logger)

        # Leader-gated slot request/release -- built now (self._resolve_leader_rpc_uri
        # and self._forward_command are bound methods, safe to reference before
        # heartbeat_subscriber itself exists, same as every other LeaderProxyHandler
        # below) so ConcurrencyClient/attach_cluster_placement can wire in right
        # after container_runtime is constructed.
        self._concurrency_slot_request_handler = LeaderProxyHandler(
            inner=ConcurrencySlotRequestHandler(ledger=self.concurrency_ledger, logger=self._logger),
            elector=self.elector,
            self_id=config.AXO_ENDPOINT_ID,
            resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
            forward_fn=self._forward_command,
            forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
            logger=self._logger,
        )
        self._concurrency_slot_release_handler = LeaderProxyHandler(
            inner=ConcurrencySlotReleaseHandler(ledger=self.concurrency_ledger, logger=self._logger),
            elector=self.elector,
            self_id=config.AXO_ENDPOINT_ID,
            resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
            forward_fn=self._forward_command,
            forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
            logger=self._logger,
        )
        self.concurrency_client = ConcurrencyClient(
            self_id=config.AXO_ENDPOINT_ID,
            slot_request_handler=self._concurrency_slot_request_handler,
            slot_release_handler=self._concurrency_slot_release_handler,
        )

        self.container_runtime = ContainerFunctionRuntime(
            function_registry = self.registry,
            summoner          = self.container_summoner,
            on_complete       = on_complete,
            config            = config,
            storage_backends  = self.storage_backends,
            data_registry     = self.data_registry,
            event_bus         = self.event_bus,
            logger            = self._logger,
        )
        self.container_runtime.attach_cluster_placement(
            concurrency_client=self.concurrency_client,
            forward_job_fn=self._forward_job_to_endpoint,
        )
        self.runtime = RuntimeDispatcher(
            registry          = self.registry,
            process_runtime   = self.process_runtime,
            container_runtime = self.container_runtime,
            logger            = self._logger,
        )
        self.result_receiver = ContainerResultReceiver(
            bind_address = config.AXO_ENDPOINT_CONTAINER_RESULT_BIND,
            on_result    = on_complete,
            logger       = self._logger,
        )

        # Job result replication (executor -> leader -> every endpoint).
        # JOB_RESULT_SYNC is leader-gated (an executor reporting a finished
        # result); JOB_RESULT_REPLICATE is the leader's own one-way push to
        # each follower, never leader-gated (mirrors STATE_SYNC_PUSH/
        # DATA_CHUNK_PUT's "receiver just stores it" shape).
        self._job_result_sync_handler = LeaderProxyHandler(
            inner=JobResultSyncHandler(
                results=self.results_store,
                consistency_store=self.result_consistency_store,
                peer_rpc_uris_fn=self._peer_rpc_uris,
                forward_fn=self._forward_command,
                max_retries=config.AXO_ENDPOINT_RESULT_REPLICATION_MAX_RETRIES,
                backoff_base_seconds=config.AXO_ENDPOINT_RESULT_REPLICATION_RETRY_BACKOFF_BASE_SECONDS,
                forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
                logger=self._logger,
            ),
            elector=self.elector,
            self_id=config.AXO_ENDPOINT_ID,
            resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
            forward_fn=self._forward_command,
            forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
            logger=self._logger,
        )
        # Now that the real handler exists, on_complete's replicate_fn
        # indirection (see above) actually does something.
        self._replicate_result_fn = make_replicate_fn(
            job_result_sync_handler=self._job_result_sync_handler,
            max_retries=config.AXO_ENDPOINT_RESULT_REPLICATION_MAX_RETRIES,
            backoff_base_seconds=config.AXO_ENDPOINT_RESULT_REPLICATION_RETRY_BACKOFF_BASE_SECONDS,
            logger=self._logger,
        )

        # Leader-owned paginated background re-verification of every job
        # result's consistency across the cluster (see CLAUDE.md's "Job
        # result replication and consistency"). Only meaningfully ticked
        # while leader -- see _result_consistency_loop.
        self.result_consistency_sweeper = ResultConsistencySweeper(
            consistency_store=self.result_consistency_store,
            reverify_fn=make_reverify_fn(
                results=self.results_store,
                consistency_store=self.result_consistency_store,
                peer_rpc_uris_fn=self._peer_rpc_uris,
                forward_fn=self._forward_command,
                max_retries=config.AXO_ENDPOINT_RESULT_REPLICATION_MAX_RETRIES,
                backoff_base_seconds=config.AXO_ENDPOINT_RESULT_REPLICATION_RETRY_BACKOFF_BASE_SECONDS,
                forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
                logger=self._logger,
            ),
            chunk_size=config.AXO_ENDPOINT_RESULT_CONSISTENCY_CHECK_CHUNK_SIZE,
        )

        self.dispatcher.register_handler(wire.JOB_RESULT_SYNC, self._job_result_sync_handler)
        self.dispatcher.register_handler(
            wire.JOB_RESULT_REPLICATE,
            JobResultReplicateHandler(
                results=self.results_store, consistency_store=self.result_consistency_store, logger=self._logger,
            ),
        )
        self.dispatcher.register_handler(
            wire.JOB_FORWARD,
            JobForwardHandler(
                runtime           = self.runtime,
                results           = self.results_store,
                event_bus         = self.event_bus,
                function_registry = self.registry,
                logger            = self._logger,
            ),
        )

        self.dispatcher.register_handler(
            wire.JOB_SUBMIT,
            JobSubmitHandler(
                runtime           = self.runtime,
                results           = self.results_store,
                event_bus         = self.event_bus,
                function_registry = self.registry,
                logger            = self._logger,
            ),
        )
        self.dispatcher.register_handler(
            wire.JOB_RESULT,
            JobResultHandler(results=self.results_store, logger=self._logger),
        )
        self.dispatcher.register_handler(wire.METRICS, MetricsHandler(metrics_provider=self._collect_metrics))
        self.dispatcher.register_handler(
            wire.ACTIVITY_LIST,
            ActivityListHandler(repository=self.activity_repository, logger=self._logger),
        )

        direct_handlers = {
            wire.PING: PingHandler(),
            wire.FUNCTION_REGISTER: LeaderProxyHandler(
                inner=FunctionRegisterHandler(registry=self.registry, event_bus=self.event_bus, logger=self._logger),
                elector=self.elector,
                self_id=config.AXO_ENDPOINT_ID,
                resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
                forward_fn=self._forward_command,
                forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
                logger=self._logger,
            ),
            # Leader-proxied like FUNCTION_REGISTER -- a delete is a catalog
            # mutation too, so a follower must proxy it, and the deletion
            # replicates via the same registry_sync tombstone path.
            wire.FUNCTION_DELETE: LeaderProxyHandler(
                inner=FunctionDeleteHandler(registry=self.registry, event_bus=self.event_bus, logger=self._logger),
                elector=self.elector,
                self_id=config.AXO_ENDPOINT_ID,
                resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
                forward_fn=self._forward_command,
                forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
                logger=self._logger,
            ),
            # Leader-proxied like FUNCTION_REGISTER/FUNCTION_DELETE -- an
            # in-place params_schema/env_vars mutation is a catalog change
            # too, replicated via the same registry_sync dirty-tracking path
            # (a plain overwrite under the existing key, no tombstone needed).
            wire.FUNCTION_UPDATE: LeaderProxyHandler(
                inner=FunctionUpdateHandler(registry=self.registry, logger=self._logger),
                elector=self.elector,
                self_id=config.AXO_ENDPOINT_ID,
                resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
                forward_fn=self._forward_command,
                forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
                logger=self._logger,
            ),
            wire.DATA_REGISTER: LeaderProxyHandler(
                inner=DataRegisterHandler(
                    registry=self.data_registry,
                    own_rpc_uri=config.AXO_ENDPOINT_ROUTER_BIND,
                    logger=self._logger,
                    bucket_registry=self.bucket_registry,
                ),
                elector=self.elector,
                self_id=config.AXO_ENDPOINT_ID,
                resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
                forward_fn=self._forward_command,
                forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
                logger=self._logger,
            ),
            # Leader-proxied like DATA_REGISTER -- a catalog mutation, so a
            # follower must proxy it, and the deletion replicates via the
            # same DataRegistrySyncBridge tombstone path (see data_sync.py).
            wire.DATA_DELETE: LeaderProxyHandler(
                inner=DataDeleteHandler(registry=self.data_registry, logger=self._logger),
                elector=self.elector,
                self_id=config.AXO_ENDPOINT_ID,
                resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
                forward_fn=self._forward_command,
                forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
                logger=self._logger,
            ),
            # Metadata-declaring registration, leader-gated like
            # FUNCTION_REGISTER/DATA_REGISTER -- DATA_REGISTER's bucket-quota
            # check (above) depends on this bucket already existing here.
            wire.BUCKET_REGISTER: LeaderProxyHandler(
                inner=BucketRegisterHandler(registry=self.bucket_registry, logger=self._logger),
                elector=self.elector,
                self_id=config.AXO_ENDPOINT_ID,
                resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
                forward_fn=self._forward_command,
                forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
                logger=self._logger,
            ),
            # Never leader-proxied -- a job runs on one specific endpoint,
            # only that endpoint's own runtime state can act on it (same
            # category as DATA_CHUNK_PUT/DATA_STATUS below).
            wire.JOB_CANCEL: JobCancelHandler(runtime=self.runtime, logger=self._logger),
            # Never leader-proxied -- the receiving node (leader, being pushed
            # to by a real client, or a follower, being pushed to by the
            # leader's replication loop) IS the intended receiver either way.
            wire.DATA_CHUNK_PUT: DataChunkPutHandler(registry=self.data_registry, logger=self._logger),
            # Never leader-proxied, same reasoning as DATA_CHUNK_PUT/
            # DATA_STATUS -- reads this specific node's own local bytes.
            wire.DATA_CHUNK_GET: DataChunkGetHandler(registry=self.data_registry, logger=self._logger),
            wire.DATA_STATUS: DataStatusHandler(registry=self.data_registry, logger=self._logger),
            wire.DATA_INFO: LeaderProxyHandler(
                inner=DataInfoHandler(registry=self.data_registry, replicator=self.blob_replicator, logger=self._logger),
                elector=self.elector,
                self_id=config.AXO_ENDPOINT_ID,
                resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
                forward_fn=self._forward_command,
                forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
                logger=self._logger,
            ),
            wire.CONTAINER_BOOTSTRAP: ContainerBootstrapHandler(registry=self.registry, logger=self._logger),
            wire.STATE_SYNC_PUSH: StateSyncPushHandler(
                state_machine=self.cluster_state_machine,
                registry_sync=self.registry_sync,
                data_registry_sync=self.data_registry_sync,
                bucket_registry_sync=self.bucket_registry_sync,
                logger=self._logger,
            ),
            wire.STATE_SYNC_PULL: StateSyncPullHandler(
                state_machine=self.cluster_state_machine,
                logger=self._logger,
            ),
            wire.CONCURRENCY_SLOT_REQUEST: self._concurrency_slot_request_handler,
            wire.CONCURRENCY_SLOT_RELEASE: self._concurrency_slot_release_handler,
            # Never leader-proxied -- reports this specific endpoint's own
            # live containers, same reasoning as DATA_STATUS/CONCURRENCY_RECONCILE_PULL.
            wire.CONCURRENCY_RECONCILE_PULL: ConcurrencyReconcilePullHandler(
                summoner=self.container_summoner, logger=self._logger,
            ),
            # Leader-gated like BUCKET_REGISTER -- only the leader owns the
            # result_consistency_sweeper this acts on.
            wire.CONSISTENCY_CHECK_REQUEST: LeaderProxyHandler(
                inner=ConsistencyCheckRequestHandler(sweeper=self.result_consistency_sweeper, logger=self._logger),
                elector=self.elector,
                self_id=config.AXO_ENDPOINT_ID,
                resolve_leader_rpc_uri=self._resolve_leader_rpc_uri,
                forward_fn=self._forward_command,
                forward_timeout_seconds=config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
                logger=self._logger,
            ),
        }

        self.heartbeat_publisher  = ZmqHeartbeatPublisher(bind_address=config.AXO_ENDPOINT_PUB_BIND)
        self.heartbeat_subscriber = ZmqHeartbeatSubscriber(
            connect_addresses=config.AXO_ENDPOINT_SUB_CONNECT,
            logger=self._logger,
            on_new_peer=self._on_new_peer,
        )

        direct_handlers[wire.PEER_ANNOUNCE] = PeerAnnounceHandler(
            subscriber=self.heartbeat_subscriber,
            local_mode=config.AXO_ENDPOINT_LOCAL_MODE,
            logger=self._logger,
        )

        self.router_server = RouterServer(
            bind_address    = config.AXO_ENDPOINT_ROUTER_BIND,
            direct_handlers = direct_handlers,
            dispatcher      = self.dispatcher,
            results         = self.results_store,
            event_bus       = self.event_bus,
            on_request_fn   = self._on_request_seen,
            logger          = self._logger,
        )

        # Keeps track of which job ids are still running.
        self._active_job_ids: Set[str] = set()
        self._active_job_ids_lock = threading.Lock()

        # Runtime-mutable -- unlike the rest of Config, this can change after
        # boot via VIRTUAL_ENV_ASSIGN (see handlers.virtual_env_assign). Reset
        # to launch config on restart; no local persistence is introduced.
        self._virtual_environment_id: Optional[str] = config.AXO_ENDPOINT_VIRTUAL_ENV_ID

        # direct_handlers is stored by reference inside RouterServer (constructed
        # above), so mutating it here still takes effect -- same trick as
        # PEER_ANNOUNCE, just deferred until _active_job_ids/_virtual_environment_id
        # actually exist for the closures below to read.
        direct_handlers[wire.VIRTUAL_ENV_ASSIGN] = VirtualEnvAssignHandler(
            active_job_ids_provider=self._snapshot_active_job_ids,
            get_virtual_environment_id=self._get_virtual_environment_id,
            set_virtual_environment_id=self._set_virtual_environment_id,
            endpoint_id=config.AXO_ENDPOINT_ID,
            external_publisher=self.external_publisher,
            logger=self._logger,
        )

        self.event_bus.subscribe("JOB_SUBMITTED", self._on_job_submitted)
        self.event_bus.subscribe("JOB_COMPLETED", self._on_job_finished)
        self.event_bus.subscribe("JOB_FAILED", self._on_job_finished)

        # Concurrency ledger: reconcile from ground truth on every leader
        # failover, and release a function's slot the instant its container
        # is torn down (idle TTL, max invocations, crash, explicit dismissal
        # -- dismiss() funnels every teardown path through this one event).
        self.event_bus.subscribe(CONSENSUS_VIEW_CHANGED_EVENT, self._on_consensus_view_changed_for_concurrency)
        self.event_bus.subscribe(CONTAINER_DISMISSED_EVENT, self._on_container_dismissed_release_slot)

        self._stop_event = threading.Event()
        self._background_threads = []
        self._start_time: float = 0.0
        # Cross-tick state for run_consensus_tick's quorum/degraded derivation
        # -- threaded in/out each call rather than held inside that function,
        # matching its existing stateless-per-call design.
        self._cluster_high_water: int = 0
        self._cluster_member_ids: Optional[FrozenSet[str]] = None
        # Updated on every inbound request (see _on_request_seen); drives the
        # blob-replication idle trigger.
        self._last_request_at: float = time.monotonic()

    def _on_request_seen(self) -> None:
        """Called by RouterServer once per handled request, regardless of
        which operation it was -- the single hook point that lets the
        blob-replication loop know how long the leader has been idle."""
        self._last_request_at = time.monotonic()

    def _on_job_submitted(self, event) -> None:
        """Adds a job id to the set of currently running jobs."""
        with self._active_job_ids_lock:
            self._active_job_ids.add(event.payload["job_id"])

    def _on_job_finished(self, event) -> None:
        """Removes a job id from the set of currently running jobs."""
        with self._active_job_ids_lock:
            self._active_job_ids.discard(event.payload["job_id"])

    def _snapshot_active_job_ids(self) -> Set[str]:
        """Thread-safe read for VirtualEnvAssignHandler's idle-gate check."""
        with self._active_job_ids_lock:
            return set(self._active_job_ids)

    def _get_virtual_environment_id(self) -> Optional[str]:
        return self._virtual_environment_id

    def _set_virtual_environment_id(self, virtual_environment_id: Optional[str]) -> None:
        self._virtual_environment_id = virtual_environment_id

    def run(self) -> None:
        """Starts the endpoint and blocks until stop() is called."""
        self._start_time = time.monotonic()
        self.router_server.start()
        if self.external_publisher is not None:
            started_event = event_models.EndpointStarted(
                endpoint_id=self.config.AXO_ENDPOINT_ID,
                router_bind=self.config.AXO_ENDPOINT_ROUTER_BIND,
                pub_bind=self.config.AXO_ENDPOINT_PUB_BIND,
                virtual_environment_id=self._virtual_environment_id,
            )
            self.external_publisher.publish(event_models.ENDPOINT_STARTED, started_event.model_dump(mode="json"))
        self.heartbeat_subscriber.start()
        self.result_receiver.start()

        heartbeat_gc_interval = max(1.0, self.config.AXO_ENDPOINT_HEARTBEAT_TTL_SECONDS / 2.0)
        self._background_threads = [
            threading.Thread(target=self._heartbeat_publish_loop, daemon=True),
            threading.Thread(
                target=run_heartbeat_gc,
                args=(
                    self.heartbeat_subscriber,
                    self.config.AXO_ENDPOINT_HEARTBEAT_TTL_SECONDS,
                    heartbeat_gc_interval,
                    self._stop_event,
                ),
                daemon=True,
            ),
            threading.Thread(target=self._worker_sweep_loop, daemon=True),
            threading.Thread(target=self._scratch_sweep_loop, daemon=True),
            threading.Thread(target=self._blob_replication_loop, daemon=True),
            threading.Thread(target=self._result_consistency_loop, daemon=True),
        ]
        for thread in self._background_threads:
            thread.start()

        self._logger.info_event(
            Event.App.STARTED,
            component    = Component.APP,
            status       = "ok",
            router_bind  = self.config.AXO_ENDPOINT_ROUTER_BIND,
            pub_bind     = self.config.AXO_ENDPOINT_PUB_BIND,
            sub_connect  = self.config.AXO_ENDPOINT_SUB_CONNECT,
            worker_count = self.config.AXO_ENDPOINT_QUEUE_WORKERS,
        )
        self._stop_event.wait()  # blocks until stop() is called

    def stop(self) -> None:
        """Shuts down the endpoint and waits for everything to stop cleanly."""
        self._stop_event.set()
        self.router_server.stop()
        self.heartbeat_subscriber.stop()
        self.heartbeat_publisher.close()

        uptime_ms = round((time.monotonic() - self._start_time) * 1000, 2) if self._start_time else 0.0
        if self.external_publisher is not None:
            stopped_event = event_models.EndpointStopped(
                endpoint_id=self.config.AXO_ENDPOINT_ID,
                virtual_environment_id=self._virtual_environment_id,
                uptime_ms=uptime_ms,
            )
            self.external_publisher.publish(event_models.ENDPOINT_STOPPED, stopped_event.model_dump(mode="json"))
            self.external_publisher.close()
        self.result_receiver.stop()
        self.dispatcher.close()
        for thread in self._background_threads:
            thread.join(timeout=2.0)

        self._logger.info_event(
            Event.App.STOPPED,
            component=Component.APP,
            status="ok",
            duration_ms=uptime_ms,
        )

    def _on_new_peer(self, info: PeerInfo) -> None:
        """Called when the heartbeat subscriber first sees a peer.

        Connects our own SUB to the peer's PUB and tells the peer to subscribe back.
        """
        if info.pub_bind:
            resolved_pub = resolve_peer_address(
                info.pub_bind, info.peer_id, self.config.AXO_ENDPOINT_LOCAL_MODE
            )
            self.heartbeat_subscriber.connect(resolved_pub)

        resolved_rpc = resolve_peer_address(
            info.rpc_uri, info.peer_id, self.config.AXO_ENDPOINT_LOCAL_MODE
        )
        self._send_peer_announce(resolved_rpc)
        self._logger.info_event(
            Event.Peer.ANNOUNCE_SENT,
            component=Component.APP,
            peer_id=info.peer_id,
            rpc_uri=resolved_rpc,
            our_pub_bind=self.config.AXO_ENDPOINT_PUB_BIND,
        )
        self._pull_state_sync(resolved_rpc)

    def _resolve_leader_rpc_uri(self, peer_id: str) -> Optional[str]:
        """Looks up a peer's resolved rpc_uri from the heartbeat subscriber --
        despite the name (kept for LeaderProxyHandler's constructor), this
        resolves any known peer id, not just the current leader; reused
        directly by _forward_job_to_endpoint below for the same reason."""
        peer = self.heartbeat_subscriber.get_peer(peer_id)
        if peer is None:
            return None
        return resolve_peer_address(peer.rpc_uri, peer.peer_id, self.config.AXO_ENDPOINT_LOCAL_MODE)

    def _peer_rpc_uris(self) -> List[str]:
        """Every other currently-known endpoint's resolved rpc_uri -- used to
        fan a job result out to "everyone else" (JobResultSyncHandler,
        ResultConsistencySweeper), same resolution as every other peer
        address use in this file."""
        return [
            resolve_peer_address(p.rpc_uri, p.peer_id, self.config.AXO_ENDPOINT_LOCAL_MODE)
            for p in self.heartbeat_subscriber.list_peers()
        ]

    def _forward_job_to_endpoint(
        self, target_endpoint_id: str, function_ref, job_id: str, params: dict,
    ) -> "Result[None, AxoError]":
        """Sends a job the leader decided should run elsewhere to its target
        endpoint via JOB_FORWARD -- ContainerFunctionRuntime's forward_job_fn."""
        rpc_uri = self._resolve_leader_rpc_uri(target_endpoint_id)
        if rpc_uri is None:
            return Err(AxoError(
                f"unknown endpoint {target_endpoint_id!r}", context={"target_endpoint_id": target_endpoint_id},
            ))
        command = Command(
            operation=wire.JOB_FORWARD,
            content_type="application/json",
            envelope={
                "function_id": function_ref.id, "function_version": function_ref.version,
                "job_id": job_id, "params": params,
            },
            payload=b"",
        )
        result = self._forward_command(rpc_uri, command, self.config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS)
        if result.is_err:
            return Err(result.unwrap_err())
        command_result = result.unwrap()
        if not command_result.ok:
            return Err(AxoError(command_result.error, context={"error_code": command_result.error_code}))
        return Ok(None)

    def _on_consensus_view_changed_for_concurrency(self, event) -> None:
        """On a role flip to leader, rebuild ConcurrencyLedger from ground
        truth -- a new leader inherits no in-memory state from whoever led
        before it. Runs on its own daemon thread: this callback fires
        synchronously inside the heartbeat loop, and reconciliation makes
        blocking network calls to every peer."""
        if event.payload.get("is_leader") and not event.payload.get("was_leader"):
            threading.Thread(target=self._reconcile_concurrency_ledger, daemon=True).start()

    def _reconcile_concurrency_ledger(self) -> None:
        self._logger.info_event(Event.Concurrency.RECONCILIATION_STARTED, component=Component.APP)
        self.concurrency_ledger.begin_reconciliation()
        own_entries = [
            ContainerCountEntry(function_id=h.function_id, version=h.version, slot_index=h.pool_index)
            for h in self.container_summoner.list_handles()
            if h.status not in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED)
        ]
        reports: Dict[str, List[ContainerCountEntry]] = {self.config.AXO_ENDPOINT_ID: own_entries}
        for peer in self.heartbeat_subscriber.list_peers():
            rpc_uri = resolve_peer_address(peer.rpc_uri, peer.peer_id, self.config.AXO_ENDPOINT_LOCAL_MODE)
            result = self._forward_command(
                rpc_uri,
                Command(operation=wire.CONCURRENCY_RECONCILE_PULL, content_type="application/json", envelope={}, payload=b""),
                self.config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
            )
            # A peer that fails/times out is treated as reporting zero this
            # round -- accepted risk, same class as every other heartbeat-
            # driven invariant here (see CLAUDE.md).
            entries: List[ContainerCountEntry] = []
            if result.is_ok and result.unwrap().ok:
                entries = [
                    ContainerCountEntry(
                        function_id=e["function_id"], version=e["version"], slot_index=e["slot_index"],
                    )
                    for e in result.unwrap().metadata.get("entries", [])
                ]
            reports[peer.peer_id] = entries
        self.concurrency_ledger.reconcile(reports)
        self._logger.info_event(
            Event.Concurrency.RECONCILIATION_FINISHED,
            component=Component.APP,
            endpoint_count=len(reports),
        )

    def _on_container_dismissed_release_slot(self, event) -> None:
        payload = event.payload
        self.concurrency_client.release(payload["function_id"], payload["version"], payload["pool_index"])

    def _forward_command(
        self, rpc_uri: str, command: Command, timeout_seconds: float
    ) -> Result[CommandResult, AxoError]:
        """Sends a command to another node and waits for its reply.

        Used by LeaderProxyHandler to forward leader-only commands, and by
        the one-shot STATE_SYNC_PULL fired on peer discovery. Returns Err on
        connect/timeout failure rather than raising.
        """
        sock = zmq.Context.instance().socket(zmq.DEALER)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(rpc_uri)
        try:
            sock.send_multipart(wire.encode_command(command))
            poller = zmq.Poller()
            poller.register(sock, zmq.POLLIN)
            events = dict(poller.poll(timeout=int(timeout_seconds * 1000)))
            if sock not in events:
                return Err(WireError(f"timed out waiting for reply from {rpc_uri}"))
            frames = sock.recv_multipart()
            return wire.decode_command_result(frames)
        finally:
            sock.close()

    def _push_state_sync(
        self,
        rpc_uri: str,
        leader_view: LeaderView,
        members: FrozenSet[str],
        mutation: StateMutation,
    ) -> None:
        """Fire-and-forget: pushes a batch of replicated function/data changes to one peer.

        Best-effort, no retry — a dropped push self-heals via the next flush
        cycle or the peer's own one-shot STATE_SYNC_PULL on rediscovery.
        """
        sock = zmq.Context.instance().socket(zmq.DEALER)
        sock.setsockopt(zmq.LINGER, 1000)
        sock.connect(rpc_uri)
        sock.send_multipart(wire.encode_command(Command(
            operation=wire.STATE_SYNC_PUSH,
            content_type="application/json",
            envelope={
                "term": leader_view.term,
                "leader_ids": list(leader_view.leader_ids),
                "members": list(members),
                "function_keys": list(mutation.function_changes.keys()),
                "data_keys": list(mutation.data_changes.keys()),
                "bucket_keys": list(mutation.bucket_changes.keys()),
            },
            payload=encode_state_changes(mutation.function_changes, mutation.data_changes, mutation.bucket_changes),
        )))
        sock.close()

    def _pull_state_sync(self, rpc_uri: str) -> None:
        """One-shot catch-up: asks a newly discovered peer for its current
        ClusterState so we don't wait for the next idle-flush cycle."""
        result = self._forward_command(
            rpc_uri,
            Command(operation=wire.STATE_SYNC_PULL, content_type="application/json", envelope={}, payload=b""),
            self.config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
        )
        if result.is_err:
            return
        command_result = result.unwrap()
        if not command_result.ok or not command_result.payload:
            return
        incoming = decode_cluster_state(command_result.payload)
        if self.cluster_state_machine.apply_remote(incoming):
            self.registry_sync.apply_incoming(incoming.functions)
            self.data_registry_sync.apply_incoming(incoming.data)
            self.bucket_registry_sync.apply_incoming(incoming.buckets)

    def _push_blob_chunk(
        self, rpc_uri: str, name: str, version: int, chunk_index: int, chunk: bytes,
    ) -> None:
        """Fire-and-forget: pushes one chunk of a registered dataset to one
        peer via DATA_CHUNK_PUT -- the exact same op a real client uses to
        push data to the leader, so client push and leader/follower
        replication share one code path end to end."""
        sock = zmq.Context.instance().socket(zmq.DEALER)
        sock.setsockopt(zmq.LINGER, 1000)
        sock.connect(rpc_uri)
        sock.send_multipart(wire.encode_command(Command(
            operation=wire.DATA_CHUNK_PUT,
            content_type="application/octet-stream",
            envelope={"name": name, "version": version, "chunk_index": chunk_index},
            payload=chunk,
        )))
        sock.close()

    def _query_data_status(self, rpc_uri: str, name: str, version: int) -> Optional[dict]:
        """Blocking request/reply: asks a peer for its own local DATA_STATUS
        for one dataset -- used by the replication loop to diff what that
        peer is missing before pushing. Returns None on any failure/timeout;
        the replicator just skips that peer/dataset this tick and tries
        again next tick."""
        result = self._forward_command(
            rpc_uri,
            Command(
                operation=wire.DATA_STATUS, content_type="application/json",
                envelope={"name": name, "version": version}, payload=b"",
            ),
            self.config.AXO_ENDPOINT_CONSENSUS_FORWARD_TIMEOUT_SECONDS,
        )
        if result.is_err:
            return None
        command_result = result.unwrap()
        if not command_result.ok:
            return None
        return command_result.metadata

    def _send_peer_announce(self, rpc_uri: str) -> None:
        """Fire-and-forget: tells a peer's router to subscribe to our PUB."""
        sock = zmq.Context.instance().socket(zmq.DEALER)
        sock.setsockopt(zmq.LINGER, 1000)
        sock.connect(rpc_uri)
        sock.send_multipart(wire.encode_command(Command(
            operation=wire.PEER_ANNOUNCE,
            content_type="application/json",
            envelope={
                "pub_bind": self.config.AXO_ENDPOINT_PUB_BIND,
                "peer_id":  self.config.AXO_ENDPOINT_ID,
            },
            payload=b"",
        )))
        sock.close()

    def _collect_metrics(self) -> dict:
        """Dispatcher counters plus the current consensus role/term -- used by both
        the METRICS operation and the periodic heartbeat log. container_pools
        rides along here so it reaches every other endpoint via the existing
        heartbeat gossip, with zero new transport -- the leader's
        ConcurrencyLedger ingests it (see _heartbeat_publish_loop) to know
        which owners currently look idle."""
        view = self.elector.current_view()
        return {
            **self.dispatcher.metrics(),
            "consensus_role": "leader" if self.elector.is_leader(self.config.AXO_ENDPOINT_ID) else "follower",
            "consensus_term": view.term,
            "consensus_leader_ids": list(view.leader_ids),
            "consensus_dirty_pending": self.dirty_tracker.pending_count(),
            "container_pools": self.container_summoner.pool_summary(),
        }

    def _heartbeat_publish_loop(self) -> None:
        """Runs in the background, sending out a heartbeat on a regular interval."""
        while not self._stop_event.is_set():
            now = time.time()
            current_metrics = self._collect_metrics()
            if self.external_publisher is not None:
                metrics_event = event_models.EndpointMetricsReported(
                    endpoint_id=self.config.AXO_ENDPOINT_ID,
                    metrics=current_metrics,
                    virtual_environment_id=self._virtual_environment_id,
                )
                self.external_publisher.publish(
                    event_models.ENDPOINT_METRICS_REPORTED, metrics_event.model_dump(mode="json"),
                )
            metrics = {
                **current_metrics,
                "__pub_bind__": self.config.AXO_ENDPOINT_PUB_BIND,
                "__sent_at__":  now,
            }
            info = PeerInfo(
                peer_id=self.config.AXO_ENDPOINT_ID,
                service_name="axo-endpoint",
                rpc_uri=self.config.AXO_ENDPOINT_ROUTER_BIND,
                metrics=metrics,
                last_seen=now,
            )
            self.heartbeat_publisher.publish(info)
            self._logger.debug_event(
                Event.App.HEARTBEAT,
                component=Component.APP,
                metrics=current_metrics,
            )
            self._cluster_high_water, self._cluster_member_ids = run_consensus_tick(
                elector=self.elector,
                heartbeat_subscriber=self.heartbeat_subscriber,
                dirty_tracker=self.dirty_tracker,
                state_machine=self.cluster_state_machine,
                self_id=self.config.AXO_ENDPOINT_ID,
                push_to_peer_fn=self._push_state_sync,
                idle_seconds=self.config.AXO_ENDPOINT_CONSENSUS_REPLICATION_IDLE_SECONDS,
                now=now,
                local_mode=self.config.AXO_ENDPOINT_LOCAL_MODE,
                logger=self._logger,
                event_bus=self.event_bus,
                high_water_mark=self._cluster_high_water,
                previous_member_ids=self._cluster_member_ids,
            )

            # Feed every known endpoint's self-reported container_pools into
            # the ledger's idle/busy view (harmless when we're not leader --
            # keeps it warm for the moment we might become leader instead of
            # starting cold) and, only while leader, reap any grant whose
            # owner has dropped out of the cluster since the last tick.
            self.concurrency_ledger.ingest_peer_metrics(
                self.config.AXO_ENDPOINT_ID, current_metrics.get("container_pools", {}),
            )
            for peer in self.heartbeat_subscriber.list_peers():
                self.concurrency_ledger.ingest_peer_metrics(peer.peer_id, peer.metrics.get("container_pools", {}))
            if self.elector.is_leader(self.config.AXO_ENDPOINT_ID) and self._cluster_member_ids is not None:
                self.concurrency_ledger.reap_unknown_owners(set(self._cluster_member_ids))

            self._stop_event.wait(self.config.AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS)

    def _worker_sweep_loop(self) -> None:
        """Runs in the background, cleaning up idle or overused workers and containers."""
        while not self._stop_event.is_set():
            now = time.time()
            self.process_runtime.sweep_idle(self.config.AXO_ENDPOINT_WORKER_IDLE_TTL_SECONDS, now)
            self.process_runtime.sweep_max_invocations(self.config.AXO_ENDPOINT_WORKER_MAX_INVOCATIONS)
            self.container_runtime.sweep_idle(self.config.AXO_ENDPOINT_WORKER_IDLE_TTL_SECONDS, now)
            self.container_runtime.sweep_max_invocations(self.config.AXO_ENDPOINT_WORKER_MAX_INVOCATIONS)
            # Required, not optional: a CRASHED handle is excluded from
            # list_handles(), so without this a function that crashes and is
            # never invoked again would leak its ConcurrencyLedger grant
            # forever -- nothing else would ever report it gone.
            self.container_summoner.sweep_crashed()
            self._stop_event.wait(self.config.AXO_ENDPOINT_WORKER_GC_INTERVAL_SECONDS)

    def _scratch_sweep_loop(self) -> None:
        """Runs in the background, deleting leftover scratch folders for jobs that are no longer active."""
        while not self._stop_event.is_set():
            with self._active_job_ids_lock:
                active = set(self._active_job_ids)
            sweep_orphaned_scratch_dirs(self.config.AXO_ENDPOINT_SCRATCH_ROOT, active)
            self._stop_event.wait(self.config.AXO_ENDPOINT_SCRATCH_GC_INTERVAL_SECONDS)

    def _blob_replication_loop(self) -> None:
        """Runs in the background, diffing every complete registered dataset
        against every peer and pushing whatever chunks that peer is missing
        -- on its own cadence, separate from the heartbeat-driven consensus
        tick, so a large dataset can't starve the small/frequent metadata
        sync traffic. Only actually ticks once the leader has been idle (no
        inbound requests) for AXO_ENDPOINT_BLOB_REPLICATION_IDLE_SECONDS --
        0 disables idle-gating (replicate on every tick)."""
        last = time.monotonic()
        while not self._stop_event.is_set():
            now = time.monotonic()
            idle_seconds = self.config.AXO_ENDPOINT_BLOB_REPLICATION_IDLE_SECONDS
            if idle_seconds <= 0 or now - self._last_request_at >= idle_seconds:
                members = [
                    ClusterMember(
                        peer_id=p.peer_id,
                        rpc_uri=resolve_peer_address(p.rpc_uri, p.peer_id, self.config.AXO_ENDPOINT_LOCAL_MODE),
                    )
                    for p in self.heartbeat_subscriber.list_peers()
                ]
                self.blob_replicator.run_tick(
                    is_leader=self.elector.is_leader(self.config.AXO_ENDPOINT_ID),
                    members=members,
                    query_status_fn=self._query_data_status,
                    push_chunk_fn=self._push_blob_chunk,
                    elapsed_seconds=now - last,
                )
            last = now
            self._stop_event.wait(self.config.AXO_ENDPOINT_CONSENSUS_BLOB_TICK_INTERVAL_SECONDS)

    def _result_consistency_loop(self) -> None:
        """Runs in the background: only while leader, ticks the paginated
        result-consistency sweep on its own configured cadence (separate
        from every other loop here, same reasoning as blob replication --
        one slow concern shouldn't starve another). A short poll interval
        just checks whether AXO_ENDPOINT_RESULT_CONSISTENCY_CHECK_INTERVAL_SECONDS
        has actually elapsed; maybe_run_periodic is a no-op otherwise."""
        while not self._stop_event.is_set():
            if self.elector.is_leader(self.config.AXO_ENDPOINT_ID):
                self.result_consistency_sweeper.maybe_run_periodic(
                    now=time.monotonic(),
                    interval_seconds=self.config.AXO_ENDPOINT_RESULT_CONSISTENCY_CHECK_INTERVAL_SECONDS,
                )
            self._stop_event.wait(min(30.0, self.config.AXO_ENDPOINT_RESULT_CONSISTENCY_CHECK_INTERVAL_SECONDS))


def build_app(config: Config) -> App:
    """Creates a new endpoint app from the given settings."""
    return App(config)
