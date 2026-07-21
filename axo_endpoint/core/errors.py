from __future__ import annotations

from axo_shared.errors import AxoError

# ── 1xxx: client / validation ─────────────────────────────────────────────────

class MissingFieldError(AxoError):
    code = 1001
    name = "MISSING_FIELD"


class InvalidFieldError(AxoError):
    code = 1002
    name = "INVALID_FIELD"


class UnknownOperationError(AxoError):
    code = 1003
    name = "UNKNOWN_OPERATION"


# ── 2xxx: not found / state ───────────────────────────────────────────────────

class FunctionNotFoundError(AxoError):
    code = 2001
    name = "FUNCTION_NOT_FOUND"


class JobNotFoundError(AxoError):
    code = 2002
    name = "JOB_NOT_FOUND"


class InvalidStateError(AxoError):
    code = 2003
    name = "INVALID_STATE_TRANSITION"


class EndpointBusyError(AxoError):
    """A VIRTUAL_ENV_ASSIGN command arrived while this endpoint has one or
    more active jobs -- reassignment is only allowed while idle."""

    code = 2004
    name = "ENDPOINT_BUSY"


# ── 3xxx: runtime / execution ─────────────────────────────────────────────────

class WorkerCrashedError(AxoError):
    code = 3001
    name = "WORKER_CRASHED"


class FunctionExecError(AxoError):
    code = 3002
    name = "FUNCTION_EXEC_FAILED"


class InvocationError(AxoError):
    code = 3003
    name = "INVOCATION_FAILED"


class ContainerError(AxoError):
    code = 3004
    name = "CONTAINER_ERROR"


class ContainerBootstrapError(AxoError):
    code = 3005
    name = "CONTAINER_BOOTSTRAP_ERROR"


class ContainerCrashError(AxoError):
    code = 3006
    name = "CONTAINER_CRASH_ERROR"


class JobTimeoutError(AxoError):
    """A job's own configured RuntimeSpec.max_duration_seconds elapsed with
    no result -- an intentional, expected outcome (the worker/container is
    presumably still alive, just over its allotted time), distinct from
    WorkerCrashedError/ContainerCrashError, which mean the worker/container
    itself died."""

    code = 3007
    name = "JOB_TIMEOUT"


# ── 4xxx: infrastructure ──────────────────────────────────────────────────────

class QueueFullError(AxoError):
    code = 4001
    name = "QUEUE_FULL"


class DispatcherClosedError(AxoError):
    code = 4002
    name = "DISPATCHER_CLOSED"


class StorageFailureError(AxoError):
    """Wire-safe wrapper a handler raises around a raw StorageBackend failure.

    Not related by inheritance to storage.backend.StorageError (code 8000) --
    see that class's docstring for why they're deliberate siblings, not a
    hierarchy.
    """

    code = 4003
    name = "STORAGE_ERROR"


# ── 5xxx: transport / wire ────────────────────────────────────────────────────
# (MalformedFrameCountError/MalformedEnvelopeError/MalformedMetadataError moved
# to axo_shared.errors — they're used by axo_shared.wire, which must not
# depend back on axo_endpoint.)

# ── 6xxx: chunked data upload ─────────────────────────────────────────────────

class DataNotRegisteredError(AxoError):
    """A chunk (or a status/read query) named a (name, version) that has
    never been through DATA_REGISTER on this node."""

    code = 6001
    name = "DATA_NOT_REGISTERED"


class ChunkIndexOutOfRangeError(AxoError):
    code = 6002
    name = "CHUNK_INDEX_OUT_OF_RANGE"


class ChunkSizeMismatchError(AxoError):
    code = 6003
    name = "CHUNK_SIZE_MISMATCH"


class StreamNotOpenError(AxoError):
    """append_chunk/finalize_stream called for a (name, version) with no
    preceding open_stream on this node."""

    code = 6004
    name = "STREAM_NOT_OPEN"


class StreamAlreadyFinalizedError(AxoError):
    code = 6005
    name = "STREAM_ALREADY_FINALIZED"


# ── 7xxx: data buckets ────────────────────────────────────────────────────────

class BucketNotFoundError(AxoError):
    """A namespaced DATA_REGISTER (or BUCKET_REGISTER lookup) named a bucket
    that has never been through BUCKET_REGISTER on this node."""

    code = 7001
    name = "BUCKET_NOT_FOUND"


class BucketAlreadyExistsError(AxoError):
    code = 7002
    name = "BUCKET_ALREADY_EXISTS"


class QuotaExceededError(AxoError):
    """A DATA_REGISTER into a bucket would push that bucket's total
    registered size over its declared quota_bytes."""

    code = 7003
    name = "QUOTA_EXCEEDED"


# ── 8xxx: job result replication ──────────────────────────────────────────────

class ResultHashMismatchError(AxoError):
    """A JOB_RESULT_SYNC/JOB_RESULT_REPLICATE payload's hash didn't match the
    hash declared alongside it -- the copy is discarded, never stored."""

    code = 8001
    name = "RESULT_HASH_MISMATCH"
