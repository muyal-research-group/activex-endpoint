from __future__ import annotations


class Component:
    APP                              = "app"
    HEARTBEAT                        = "heartbeat"
    ROUTER                           = "router"
    DISPATCHER                       = "dispatcher"
    RUNTIME                          = "runtime"
    HANDLER_JOB_SUBMIT               = "handler.job_submit"
    HANDLER_JOB_RESULT               = "handler.job_result"
    HANDLER_FUNCTION_REGISTER        = "handler.function_register"
    HANDLER_FUNCTION_UPDATE          = "handler.function_update"
    HANDLER_FUNCTION_DELETE          = "handler.function_delete"
    HANDLER_DATA_REGISTER            = "handler.data_register"
    HANDLER_DATA_DELETE              = "handler.data_delete"
    HANDLER_DATA_CHUNK_PUT           = "handler.data_chunk_put"
    HANDLER_DATA_CHUNK_GET           = "handler.data_chunk_get"
    HANDLER_DATA_STATUS              = "handler.data_status"
    HANDLER_DATA_INFO                = "handler.data_info"
    HANDLER_BUCKET_REGISTER          = "handler.bucket_register"
    HANDLER_PEER_ANNOUNCE            = "handler.peer_announce"
    HANDLER_CONTAINER_BOOTSTRAP      = "handler.container_bootstrap"
    CONTAINER_RUNTIME                = "container_runtime"
    CONTAINER_SPAWNER                = "container_spawner"
    CONTAINER_RUNNER                 = "container_runner"
    RESULT_RECEIVER                  = "result_receiver"
    CONSENSUS                        = "consensus"
    HANDLER_STATE_SYNC_PUSH          = "handler.state_sync_push"
    HANDLER_STATE_SYNC_PULL          = "handler.state_sync_pull"
    HANDLER_LEADER_PROXY             = "handler.leader_proxy"
    DATAIO                           = "dataio"
    BLOB_REPLICATION                 = "blob_replication"
    HANDLER_ACTIVITY_LIST            = "handler.activity_list"
    EXTERNAL_FORWARDING              = "external_forwarding"
    HANDLER_VIRTUAL_ENV_ASSIGN       = "handler.virtual_env_assign"
    CONCURRENCY_LEDGER               = "concurrency_ledger"
    HANDLER_CONCURRENCY_SLOT_REQUEST = "handler.concurrency_slot_request"
    HANDLER_CONCURRENCY_SLOT_RELEASE = "handler.concurrency_slot_release"
    HANDLER_CONCURRENCY_RECONCILE_PULL = "handler.concurrency_reconcile_pull"
    HANDLER_JOB_FORWARD              = "handler.job_forward"
    HANDLER_JOB_RESULT_SYNC          = "handler.job_result_sync"
    HANDLER_CONSISTENCY_CHECK_REQUEST = "handler.consistency_check_request"
    RESULT_CONSISTENCY               = "result_consistency"
    HANDLER_JOB_CANCEL               = "handler.job_cancel"


class Event:
    class App:
        STARTED   = "APP.STARTED"
        STOPPED   = "APP.STOPPED"
        HEARTBEAT = "APP.HEARTBEAT"

    class Heartbeat:
        SUBSCRIBER_STARTED = "HEARTBEAT.SUBSCRIBER_STARTED"
        SUBSCRIBER_STOPPED = "HEARTBEAT.SUBSCRIBER_STOPPED"
        FRAME_DROPPED      = "HEARTBEAT.FRAME_DROPPED"
        DECODE_ERROR       = "HEARTBEAT.DECODE_ERROR"

    class Peer:
        DISCOVERED        = "PEER.DISCOVERED"
        HEARTBEAT         = "PEER.HEARTBEAT"
        EVICTED           = "PEER.EVICTED"
        ANNOUNCE_SENT     = "PEER.ANNOUNCE_SENT"
        ANNOUNCE_RECEIVED = "PEER.ANNOUNCE_RECEIVED"

    class Router:
        REQUEST_DROPPED    = "ROUTER.REQUEST_DROPPED"
        REQUEST_RECEIVED   = "ROUTER.REQUEST_RECEIVED"
        REQUEST_HANDLED    = "ROUTER.REQUEST_HANDLED"
        REQUEST_DISPATCHED = "ROUTER.REQUEST_DISPATCHED"
        PUSH_SKIPPED       = "ROUTER.PUSH_SKIPPED"
        PUSH_SENT          = "ROUTER.PUSH_SENT"

    class Dispatcher:
        CLOSED            = "DISPATCHER.CLOSED"
        UNKNOWN_OPERATION = "DISPATCHER.UNKNOWN_OPERATION"
        QUEUE_FULL        = "DISPATCHER.QUEUE_FULL"
        HANDLER_EXC       = "DISPATCHER.HANDLER_EXC"

    class Runtime:
        JOB_INVOKED    = "RUNTIME.JOB_INVOKED"
        WORKER_SPAWNED = "RUNTIME.WORKER_SPAWNED"
        WORKER_REAPED  = "RUNTIME.WORKER_REAPED"
        WORKER_CRASHED = "RUNTIME.WORKER_CRASHED"
        WORKER_JOB_TIMEOUT = "RUNTIME.WORKER_JOB_TIMEOUT"
        WORKER_CANCELLED = "RUNTIME.WORKER_CANCELLED"

    class Job:
        SUBMITTED    = "JOB.SUBMITTED"
        COMPLETED    = "JOB.COMPLETED"
        FAILED       = "JOB.FAILED"
        RESULT_POLLED = "JOB.RESULT_POLLED"
        RETRY_SCHEDULED = "JOB.RETRY_SCHEDULED"
        RETRY_EXHAUSTED = "JOB.RETRY_EXHAUSTED"
        CANCEL_REQUESTED = "JOB.CANCEL_REQUESTED"

    class Function:
        REGISTERED = "FUNCTION.REGISTERED"
        UPDATED    = "FUNCTION.UPDATED"
        DELETED    = "FUNCTION.DELETED"

    class Data:
        REGISTERED       = "DATA.REGISTERED"
        DELETED          = "DATA.DELETED"
        CHUNK_STORED     = "DATA.CHUNK_STORED"
        CHUNK_READ       = "DATA.CHUNK_READ"
        STATUS_QUERIED   = "DATA.STATUS_QUERIED"
        INFO_QUERIED     = "DATA.INFO_QUERIED"
        STREAM_OPENED    = "DATA.STREAM_OPENED"
        STREAM_FINALIZED = "DATA.STREAM_FINALIZED"
        REPLICATION_COMPLETE = "DATA.REPLICATION_COMPLETE"

    class Bucket:
        REGISTERED = "BUCKET.REGISTERED"

    class DataIO:
        REQUEST_RECEIVED = "DATAIO.REQUEST_RECEIVED"
        REQUEST_RESOLVED = "DATAIO.REQUEST_RESOLVED"
        REQUEST_FAILED   = "DATAIO.REQUEST_FAILED"

    class Consensus:
        TICK                   = "CONSENSUS.TICK"
        LEADER_ELECTED         = "CONSENSUS.LEADER_ELECTED"
        STEPPED_DOWN           = "CONSENSUS.STEPPED_DOWN"
        REPLICATION_FLUSHED    = "CONSENSUS.REPLICATION_FLUSHED"
        SYNC_PUSH_RECEIVED     = "CONSENSUS.SYNC_PUSH_RECEIVED"
        SYNC_PUSH_REJECTED     = "CONSENSUS.SYNC_PUSH_REJECTED"
        SYNC_PULL_SERVED       = "CONSENSUS.SYNC_PULL_SERVED"
        REQUEST_FORWARDED      = "CONSENSUS.REQUEST_FORWARDED"
        REQUEST_FORWARD_FAILED = "CONSENSUS.REQUEST_FORWARD_FAILED"
        QUORUM_LOST            = "CONSENSUS.QUORUM_LOST"
        QUORUM_RESTORED        = "CONSENSUS.QUORUM_RESTORED"
        DEGRADED               = "CONSENSUS.DEGRADED"

    class Activity:
        LISTED = "ACTIVITY.LISTED"

    class VirtualEnv:
        ASSIGNED       = "VIRTUAL_ENV.ASSIGNED"
        DETACHED       = "VIRTUAL_ENV.DETACHED"
        ASSIGN_REJECTED = "VIRTUAL_ENV.ASSIGN_REJECTED"

    class External:
        PUBLISHED             = "EXTERNAL.PUBLISHED"
        PUBLISH_FAILED        = "EXTERNAL.PUBLISH_FAILED"
        VERSION_UNKNOWN_SKIPPED = "EXTERNAL.VERSION_UNKNOWN_SKIPPED"

    class Container:
        SPAWNED             = "CONTAINER.SPAWNED"
        READY               = "CONTAINER.READY"
        DISMISSED           = "CONTAINER.DISMISSED"
        CRASHED             = "CONTAINER.CRASHED"
        JOB_TIMEOUT         = "CONTAINER.JOB_TIMEOUT"
        JOB_CANCELLED       = "CONTAINER.JOB_CANCELLED"
        BOOTSTRAP_REQUESTED = "CONTAINER.BOOTSTRAP_REQUESTED"
        BOOTSTRAP_COMPLETE  = "CONTAINER.BOOTSTRAP_COMPLETE"
        JOB_DISPATCHED      = "CONTAINER.JOB_DISPATCHED"
        JOB_RECEIVED        = "CONTAINER.JOB_RECEIVED"
        RESULT_PUSHED       = "CONTAINER.RESULT_PUSHED"
        BUILD_STARTED       = "CONTAINER.BUILD_STARTED"
        BUILD_COMPLETE      = "CONTAINER.BUILD_COMPLETE"

    class Concurrency:
        SLOT_GRANTED            = "CONCURRENCY.SLOT_GRANTED"
        SLOT_AT_CAPACITY        = "CONCURRENCY.SLOT_AT_CAPACITY"
        SLOT_RELEASED           = "CONCURRENCY.SLOT_RELEASED"
        JOB_FORWARDED           = "CONCURRENCY.JOB_FORWARDED"
        RECONCILIATION_STARTED  = "CONCURRENCY.RECONCILIATION_STARTED"
        RECONCILIATION_FINISHED = "CONCURRENCY.RECONCILIATION_FINISHED"

    class ResultConsistency:
        REPLICATION_STARTED   = "RESULT_CONSISTENCY.REPLICATION_STARTED"
        REPLICATION_SUCCEEDED = "RESULT_CONSISTENCY.REPLICATION_SUCCEEDED"
        REPLICATION_FAILED    = "RESULT_CONSISTENCY.REPLICATION_FAILED"
        FANOUT_FAILED         = "RESULT_CONSISTENCY.FANOUT_FAILED"
        RESULT_RECEIVED       = "RESULT_CONSISTENCY.RESULT_RECEIVED"
        HASH_MISMATCH         = "RESULT_CONSISTENCY.HASH_MISMATCH"
        CHECK_STARTED         = "RESULT_CONSISTENCY.CHECK_STARTED"
        CHECK_FINISHED        = "RESULT_CONSISTENCY.CHECK_FINISHED"
