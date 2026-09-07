from __future__ import annotations

import hashlib
from typing import Callable, List, Optional, Union

from option import Result

from axo_shared.errors import AxoError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_shared import wire
from axo_endpoint.core.consensus.result_consistency import ResultConsistencyStore, push_with_retry
from axo_endpoint.core.errors import MissingFieldError, ResultHashMismatchError
from axo_endpoint.core.results import FunctionResult, decode_function_result, encode_function_result
from axo_endpoint.core.storage.backend import StorageBackend, StorageKey
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]
# rpc_uri, Command, timeout_seconds -> Result[CommandResult, AxoError]
ForwardFn = Callable[[str, Command, float], "Result[CommandResult, AxoError]"]
PeerRpcUrisFn = Callable[[], List[str]]


def fanout_result_to_peers(
    job_id: str,
    payload: bytes,
    result_hash: str,
    peer_rpc_uris: List[str],
    forward_fn: ForwardFn,
    max_retries: int,
    backoff_base_seconds: float,
    forward_timeout_seconds: float,
    logger: _Logger,
) -> None:
    """Pushes one job's result to every given peer, retrying each with
    exponential backoff independently. Shared by the eager path (right after
    an executor's result reaches the leader) and the periodic consistency
    sweep's re-verification pass (which just re-pushes -- each receiver's own
    hash check on receipt is what actually re-verifies/self-heals a drifted
    copy, so this one function is the whole "sync again" mechanism either way."""
    for rpc_uri in peer_rpc_uris:
        command = Command(
            operation=wire.JOB_RESULT_REPLICATE,
            content_type="application/octet-stream",
            envelope={"job_id": job_id, "hash": result_hash},
            payload=payload,
        )

        def attempt(rpc_uri=rpc_uri, command=command) -> bool:
            result = forward_fn(rpc_uri, command, forward_timeout_seconds)
            return result.is_ok and result.unwrap().ok

        ok = push_with_retry(attempt, max_retries, backoff_base_seconds)
        if ok:
            logger.debug_event(
                Event.ResultConsistency.REPLICATION_SUCCEEDED,
                component=Component.HANDLER_JOB_RESULT_SYNC,
                job_id=job_id,
                rpc_uri=rpc_uri,
            )
        else:
            logger.warning_event(
                Event.ResultConsistency.FANOUT_FAILED,
                component=Component.HANDLER_JOB_RESULT_SYNC,
                job_id=job_id,
                rpc_uri=rpc_uri,
            )


def make_reverify_fn(
    results: StorageBackend,
    consistency_store: ResultConsistencyStore,
    peer_rpc_uris_fn: PeerRpcUrisFn,
    forward_fn: ForwardFn,
    max_retries: int,
    backoff_base_seconds: float,
    forward_timeout_seconds: float,
    logger: _Logger = None,
) -> Callable[[str], None]:
    """Builds the ResultConsistencySweeper's reverify_fn callback: re-pushes
    one job's canonical result to every peer -- the periodic sweep's
    correction mechanism for any endpoint whose copy has drifted."""
    _logger: _Logger = logger or DumbLogger()

    def reverify(job_id: str) -> None:
        get_result = results.get(StorageKey(id=job_id))
        if get_result.is_err or get_result.unwrap() is None:
            return
        result = get_result.unwrap()
        payload = encode_function_result(result)
        result_hash = consistency_store.get_hash(job_id) or hashlib.sha256(payload).hexdigest()
        fanout_result_to_peers(
            job_id, payload, result_hash, peer_rpc_uris_fn(), forward_fn,
            max_retries, backoff_base_seconds, forward_timeout_seconds, _logger,
        )

    return reverify


def make_replicate_fn(
    job_result_sync_handler: CommandHandler,
    max_retries: int,
    backoff_base_seconds: float,
    logger: _Logger = None,
) -> Callable[[FunctionResult], None]:
    """Builds build_completion_recorder's replicate_fn: pushes one just-
    completed job's result to this endpoint's own (LeaderProxyHandler-wrapped)
    JOB_RESULT_SYNC handler -- an in-process call if this endpoint is
    leader, or one real wire forward to whoever is, either way retried with
    exponential backoff here (LeaderProxyHandler itself only ever makes one
    attempt per call)."""
    _logger: _Logger = logger or DumbLogger()

    def replicate(result: FunctionResult) -> None:
        try:
            payload = encode_function_result(result)
        except Exception as exc:  # defensive -- must never crash on_complete's caller
            _logger.error_event(
                Event.ResultConsistency.REPLICATION_FAILED,
                component=Component.HANDLER_JOB_RESULT_SYNC,
                job_id=result.job_id,
                error_message=str(exc),
            )
            return

        result_hash = hashlib.sha256(payload).hexdigest()
        command = Command(
            operation=wire.JOB_RESULT_SYNC,
            content_type="application/octet-stream",
            envelope={"job_id": result.job_id, "hash": result_hash},
            payload=payload,
        )
        _logger.debug_event(
            Event.ResultConsistency.REPLICATION_STARTED,
            component=Component.HANDLER_JOB_RESULT_SYNC,
            job_id=result.job_id,
        )

        def attempt() -> bool:
            return job_result_sync_handler.handle(command).ok

        ok = push_with_retry(attempt, max_retries, backoff_base_seconds)
        if ok:
            _logger.info_event(
                Event.ResultConsistency.REPLICATION_SUCCEEDED,
                component=Component.HANDLER_JOB_RESULT_SYNC,
                job_id=result.job_id,
            )
        else:
            _logger.error_event(
                Event.ResultConsistency.REPLICATION_FAILED,
                component=Component.HANDLER_JOB_RESULT_SYNC,
                job_id=result.job_id,
            )

    return replicate


class JobResultSyncHandler(CommandHandler):
    """Leader-side: an executor reports one finished job's result. Always
    wrapped in LeaderProxyHandler -- only ever runs for real on whoever is
    currently leader. Verifies the hash, stores its own copy, then fans the
    same payload out to every other endpoint via JOB_RESULT_REPLICATE."""

    def __init__(
        self,
        results: StorageBackend,
        consistency_store: ResultConsistencyStore,
        peer_rpc_uris_fn: PeerRpcUrisFn,
        forward_fn: ForwardFn,
        max_retries: int,
        backoff_base_seconds: float,
        forward_timeout_seconds: float,
        logger: _Logger = None,
    ) -> None:
        self._results = results
        self._consistency_store = consistency_store
        self._peer_rpc_uris_fn = peer_rpc_uris_fn
        self._forward_fn = forward_fn
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._forward_timeout_seconds = forward_timeout_seconds
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        job_id = command.envelope.get("job_id")
        expected_hash = command.envelope.get("hash")
        if not job_id or not expected_hash:
            err = MissingFieldError("job_id and hash are required", context={"fields": ["job_id", "hash"]})
            return CommandResult.from_error(err)

        payload = command.payload
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_hash != expected_hash:
            self._logger.warning_event(
                Event.ResultConsistency.HASH_MISMATCH,
                component=Component.HANDLER_JOB_RESULT_SYNC,
                job_id=job_id,
            )
            return CommandResult.from_error(
                ResultHashMismatchError("result payload hash mismatch", context={"job_id": job_id})
            )

        result = decode_function_result(payload)
        self._results.put(StorageKey(id=job_id), result)
        self._consistency_store.mark_synced(job_id, actual_hash)
        self._logger.info_event(
            Event.ResultConsistency.RESULT_RECEIVED,
            component=Component.HANDLER_JOB_RESULT_SYNC,
            job_id=job_id,
        )

        fanout_result_to_peers(
            job_id, payload, actual_hash, self._peer_rpc_uris_fn(), self._forward_fn,
            self._max_retries, self._backoff_base_seconds, self._forward_timeout_seconds, self._logger,
        )
        return CommandResult(ok=True)


class JobResultReplicateHandler(CommandHandler):
    """Receiver-side: the leader pushed one job's result to this endpoint.
    Plain direct handler, never leader-gated -- this endpoint just verifies
    the hash and stores its own copy, it doesn't forward further."""

    def __init__(
        self,
        results: StorageBackend,
        consistency_store: ResultConsistencyStore,
        logger: _Logger = None,
    ) -> None:
        self._results = results
        self._consistency_store = consistency_store
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        job_id = command.envelope.get("job_id")
        expected_hash = command.envelope.get("hash")
        if not job_id or not expected_hash:
            err = MissingFieldError("job_id and hash are required", context={"fields": ["job_id", "hash"]})
            return CommandResult.from_error(err)

        payload = command.payload
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_hash != expected_hash:
            self._consistency_store.mark_inconsistent(job_id)
            self._logger.warning_event(
                Event.ResultConsistency.HASH_MISMATCH,
                component=Component.HANDLER_JOB_RESULT_SYNC,
                job_id=job_id,
            )
            return CommandResult.from_error(
                ResultHashMismatchError("result payload hash mismatch", context={"job_id": job_id})
            )

        result = decode_function_result(payload)
        self._results.put(StorageKey(id=job_id), result)
        self._consistency_store.mark_synced(job_id, actual_hash)
        self._logger.info_event(
            Event.ResultConsistency.RESULT_RECEIVED,
            component=Component.HANDLER_JOB_RESULT_SYNC,
            job_id=job_id,
        )
        return CommandResult(ok=True)
