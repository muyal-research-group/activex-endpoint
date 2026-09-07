from __future__ import annotations

import dataclasses
import json
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Union

import zmq
from option import Err, Ok, Result
from zmq.utils.monitor import recv_monitor_message

from axo_shared.activity.models import JOB_STARTED_EVENT
from axo_shared.errors import AxoError
from axo_shared.runtime.spec import RuntimeSpec
from axo_endpoint.config import Config
from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.dataio import IORef, resolve_io_request
from axo_endpoint.core.errors import (
    ContainerCrashError,
    ContainerError,
    InvocationError,
    JobCancelledError,
    JobTimeoutError,
)
from axo_endpoint.core.events.bus import Event as BusEvent, EventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.runtime.base import FunctionRuntime, FunctionRuntimeError, InvocationHandle
from axo_endpoint.core.storage.backend import StorageBackend, StorageKey
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event
from axo_endpoint.service.container.handle import ContainerHandle, ContainerStatus
from axo_endpoint.service.container.spawner import ContainerSummoner
from axo_endpoint.service.runtime.concurrency_client import ConcurrencyClient

_Logger = Union[Log, DumbLogger]
OnComplete = Callable[[InvocationHandle, Result[Any, FunctionRuntimeError], Optional[List[str]]], None]
# target_endpoint_id, function_ref, job_id, params -> Ok(None) once forwarded
ForwardJobFn = Callable[[str, StorageKey, str, Dict[str, Any]], Result[None, AxoError]]
OnForwarded = Callable[[str, str], None]  # job_id, target_endpoint_id

# Heartbeat the pump's DEALER socket so a genuinely dead container (process
# killed, host vanished) is detected via EVENT_DISCONNECTED independent of
# any one job's own max_duration_seconds -- a plain DEALER/ROUTER TCP pair
# can otherwise sit on a half-open connection for a long time (OS-dependent)
# before recv() ever reflects that the peer is actually gone.
_HEARTBEAT_IVL_MS = 1000
_HEARTBEAT_TIMEOUT_MS = 3000
_HEARTBEAT_TTL_MS = 4000
# Short and polled repeatedly (not one long blocking wait) so a job's own
# max_duration_seconds deadline and the disconnect flag both get checked
# promptly instead of only once every 30s.
_RECV_POLL_MS = 1000

# ZMQ frame layout for job dispatch to container (endpoint = DEALER, container = ROUTER):
# dispatch (endpoint->container):    [b"dispatch", job_id, scratch_dir, params_json]
# io_request (container->endpoint):  [b"io_request", request_id, op, ref_json, data]
# io_reply (endpoint->container):    [b"io_reply", request_id, status, payload]
# result (container->endpoint):      [b"result", job_id, status, payload_json]
# (ROUTER auto-prepends/strips the peer identity frame on its side of each hop)


class ContainerFunctionRuntime(FunctionRuntime):
    """Runs functions in Docker containers or Swarm services."""

    def __init__(
        self,
        function_registry: FunctionRegistry,
        summoner: ContainerSummoner,
        on_complete: OnComplete,
        config: Config,
        storage_backends: Optional[Dict[str, StorageBackend]] = None,
        data_registry: Optional[DataRegistry] = None,
        event_bus: Optional[EventBus] = None,
        logger: _Logger = None,
    ) -> None:
        self._registry = function_registry
        self._summoner = summoner
        self._on_complete = on_complete
        self._config = config
        self._storage_backends = storage_backends or {}
        self._data_registry = data_registry
        self._event_bus = event_bus
        self._logger: _Logger = logger or DumbLogger()

        # One ZMQ context shared across all pump threads
        self._zmq_ctx = zmq.Context.instance()

        # One pump thread + DEALER socket per ContainerHandle
        self._pump_threads: Dict[str, threading.Thread] = {}
        self._pump_threads_lock = threading.Lock()

        # job_id -> retries already used. Only ever gains an entry the first
        # time a job needs a retry (a job that never crashes never touches
        # this) and loses it once that job reaches a terminal outcome --
        # either it exhausts its retries and fails, or it eventually succeeds
        # (see _pump_one_job's success branch).
        self._attempts: Dict[str, int] = {}
        self._attempts_lock = threading.Lock()

        # Cluster-wide placement -- unset until attach_cluster_placement() is
        # called (e.g. by App, once its heartbeat/leader-proxy collaborators
        # exist). Left unset, invoke() falls back to summoner.summon()'s
        # original, unchanged single-endpoint behavior -- so any caller that
        # never wires this in (including today's existing tests) sees no
        # behavior change at all.
        self._concurrency_client: Optional[ConcurrencyClient] = None
        self._forward_job_fn: Optional[ForwardJobFn] = None
        self._on_forwarded: Optional[OnForwarded] = None

    def attach_cluster_placement(
        self,
        concurrency_client: ConcurrencyClient,
        forward_job_fn: ForwardJobFn,
        on_forwarded: Optional[OnForwarded] = None,
    ) -> None:
        """Enables cluster-wide placement: local reuse still tried first,
        but a local miss now asks the leader (via concurrency_client)
        instead of growing an unbounded per-endpoint pool. Called once from
        App after its heartbeat/leader-proxy collaborators exist."""
        self._concurrency_client = concurrency_client
        self._forward_job_fn = forward_job_fn
        self._on_forwarded = on_forwarded

    def invoke(
        self,
        function_ref: StorageKey,
        job_id: str,
        params: Dict[str, Any],
    ) -> Result[InvocationHandle, FunctionRuntimeError]:
        t0 = time.monotonic()

        # Resolve runtime_spec from the registry
        get_result = self._registry.get(function_ref)
        if get_result.is_err or get_result.unwrap() is None:
            err = InvocationError(
                f"function {function_ref.id!r} not found",
                context={"function_id": function_ref.id},
            )
            return Err(err)

        record = get_result.unwrap()
        spec = record.runtime_spec

        if self._concurrency_client is None:
            # Cluster placement never wired in -- summon() alone still does
            # reuse/queue/growth exactly as it always has, unchanged.
            summon_result = self._summoner.summon(function_ref.id, function_ref.version or 0, spec)
            if summon_result.is_err:
                raw = summon_result.unwrap_err()
                return Err(InvocationError(str(raw), context={"function_id": function_ref.id}))
            handle = summon_result.unwrap()
        else:
            placement_result = self._resolve_placement(function_ref, job_id, params, spec)
            if placement_result.is_err:
                return Err(placement_result.unwrap_err())
            handle = placement_result.unwrap()
            if handle is None:
                # Forwarded to a different endpoint -- nothing left to
                # dispatch here. That endpoint's own on_complete/JOB_COMPLETED
                # is what eventually resolves this job_id; this endpoint's own
                # local result stays PENDING until the replicated terminal
                # result arrives (see job result replication).
                duration_ms = round((time.monotonic() - t0) * 1000, 2)
                self._logger.info_event(
                    Event.Concurrency.JOB_FORWARDED,
                    component=Component.CONTAINER_RUNTIME,
                    status="ok",
                    job_id=job_id,
                    function_id=function_ref.id,
                    duration_ms=duration_ms,
                )
                return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id, version=function_ref.version))

        # Create scratch directory
        scratch_dir = self._alloc_scratch(job_id)

        # `ready_event` stays set forever once the container has *ever*
        # become ready -- checking it (not handle.status == READY) is what
        # correctly handles warm re-invocation: status flips to BUSY/IDLE
        # after the first job and never back to READY, so a naive status
        # check would wrongly reject every invocation after the first.
        # `_poll_readiness` also sets ready_event on its own timeout path
        # (with status=CRASHED, "unblock waiters"), so CRASHED/DISMISSED must
        # still be excluded here.
        if handle.ready_event.is_set() and handle.status not in (
            ContainerStatus.CRASHED, ContainerStatus.DISMISSED
        ):
            # Already ready (or became ready between get_handle() and here) --
            # dispatch synchronously, same as today's happy path.
            self._ensure_pump(handle)
            self._enqueue_job(handle, job_id, scratch_dir, params)
        else:
            # Cold start: do NOT block this thread waiting for readiness.
            # This may be the RouterServer's own single receive-loop thread
            # (via InMemoryCommandDispatcher.submit()'s blocking future.result())
            # -- blocking here would deadlock the container's own
            # CONTAINER_BOOTSTRAP request, which needs a reply from that exact
            # same thread to ever become ready. A background thread waits
            # instead and enqueues once ready, or reports failure via
            # on_complete (the same path every other post-dispatch failure
            # already uses) if it never becomes ready.
            #
            # Claim the handle as BUSY right now, synchronously -- not just
            # once the background thread eventually calls _enqueue_job.
            # Otherwise a still-cold handle looks "available" to summon()'s
            # pool selection for as long as it takes to become ready (can be
            # seconds), so a second concurrent invoke() for the same
            # function would pile onto this same not-yet-ready container
            # instead of growing the pool.
            with handle._lock:
                if handle.status not in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED):
                    handle.status = ContainerStatus.BUSY
            threading.Thread(
                target=self._dispatch_once_ready,
                args=(handle, function_ref.id, job_id, scratch_dir, params),
                daemon=True,
            ).start()

        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            Event.Container.JOB_DISPATCHED,
            component=Component.CONTAINER_RUNTIME,
            status="ok",
            job_id=job_id,
            function_id=function_ref.id,
            service_name=handle.service_name,
            duration_ms=duration_ms,
        )
        return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id, version=function_ref.version))

    def _resolve_placement(
        self,
        function_ref: StorageKey,
        job_id: str,
        params: Dict[str, Any],
        spec: RuntimeSpec,
    ) -> Result[Optional[ContainerHandle], FunctionRuntimeError]:
        """Decides where this job runs when cluster placement is enabled:
        local reuse first (no network), else ask the leader. 'granted' grows
        a new local container at the assigned index; 'place' targeting this
        same endpoint means it already owns every slot for this function, so
        the job just queues behind its own least-busy member; 'place'
        targeting anyone else forwards the job there and returns None (no
        local handle to dispatch to). 'retry' surfaces as a retryable error."""
        function_id = function_ref.id
        version = function_ref.version or 0

        handle = self._summoner.find_idle(function_id, version)
        if handle is not None:
            return Ok(handle)

        decision_result = self._concurrency_client.request_growth(function_id, version, spec.max_concurrency)
        if decision_result.is_err:
            return Err(InvocationError(str(decision_result.unwrap_err()), context={"function_id": function_id}))
        decision = decision_result.unwrap()

        if decision.action == "retry":
            return Err(InvocationError(
                "cluster concurrency ledger is mid-reconciliation, retry shortly",
                context={"function_id": function_id},
            ))

        if decision.action == "granted":
            summon_result = self._summoner.summon_at(function_id, version, spec, decision.slot_index)
            if summon_result.is_err:
                # The ledger already committed this grant before we tried to
                # actually spawn anything -- if the spawn itself fails (image
                # error, Docker daemon hiccup, name conflict, ...), release it
                # right back. Otherwise the ledger permanently believes this
                # endpoint owns a slot that was never backed by a real
                # container, and every future job for this function gets
                # routed to "place with yourself" -> least_busy() finds
                # nothing -> a permanent, self-inflicted dead end.
                self._concurrency_client.release(function_id, version, decision.slot_index)
                return Err(InvocationError(str(summon_result.unwrap_err()), context={"function_id": function_id}))
            return Ok(summon_result.unwrap())

        # action == "place"
        if decision.target_endpoint_id == self._concurrency_client.self_id:
            local_handle = self._summoner.least_busy(function_id, version)
            if local_handle is None:
                return Err(InvocationError(
                    "leader named this endpoint as owner but no local container exists",
                    context={"function_id": function_id},
                ))
            return Ok(local_handle)

        forward_result = self._forward_job_fn(decision.target_endpoint_id, function_ref, job_id, params)
        if forward_result.is_err:
            return Err(InvocationError(str(forward_result.unwrap_err()), context={"function_id": function_id}))
        if self._on_forwarded is not None:
            self._on_forwarded(job_id, decision.target_endpoint_id)
        return Ok(None)

    def _dispatch_once_ready(
        self,
        handle: ContainerHandle,
        function_id: str,
        job_id: str,
        scratch_dir: str,
        params: Dict[str, Any],
    ) -> None:
        """Runs on its own daemon thread for a cold-started container. By the
        time this runs, invoke() has already returned Ok(...) -- this is the
        only place a cold-start readiness failure can still be reported."""
        timeout = self._config.AXO_ENDPOINT_CONTAINER_READINESS_TIMEOUT_SECONDS
        handle.ready_event.wait(timeout=timeout)
        if not handle.ready_event.is_set() or handle.status in (
            ContainerStatus.CRASHED, ContainerStatus.DISMISSED
        ):
            err = ContainerError(
                f"container for {function_id!r} did not become ready",
                context={"function_id": function_id, "status": handle.status},
            )
            self._on_complete(
                InvocationHandle(job_id=job_id, function_id=function_id, version=handle.version), Err(err),
            )
            return
        self._ensure_pump(handle)
        self._enqueue_job(handle, job_id, scratch_dir, params)

    def _enqueue_job(
        self, handle: ContainerHandle, job_id: str, scratch_dir: str, params: Dict[str, Any],
    ) -> None:
        if not hasattr(handle, "_job_queue"):
            import queue
            handle._job_queue = queue.Queue()

        with handle._lock:
            handle.status = ContainerStatus.BUSY
            handle.last_used = time.time()
            handle.invocation_count += 1

        handle._job_queue.put((job_id, scratch_dir, params))

    def sweep_idle(self, ttl_seconds: float, now: float) -> List[str]:
        return self._summoner.sweep_idle(ttl_seconds, now)

    def sweep_max_invocations(self, max_invocations: int) -> List[str]:
        return self._summoner.sweep_max_invocations(max_invocations)

    def cancel(self, job_id: str) -> bool:
        """Stops job_id: dismisses its container (same teardown _handle_crash
        uses) if it's currently in flight, or drops it in place from
        whichever container's queue it's still waiting behind. Bypasses
        _retry_or_finalize entirely -- a deliberate cancel must never
        trigger a retry, unlike a real crash/timeout."""
        for handle in self._summoner.list_handles():
            if handle.current_job_id == job_id:
                with handle._lock:
                    handle.status = ContainerStatus.CRASHED
                self._logger.info_event(
                    Event.Container.JOB_CANCELLED,
                    component=Component.CONTAINER_RUNTIME,
                    function_id=handle.function_id,
                    service_name=handle.service_name,
                    job_id=job_id,
                )
                self._summoner.dismiss(handle, reason="cancelled")
                if self._concurrency_client is not None:
                    self._concurrency_client.release(handle.function_id, handle.version, handle.pool_index)
                with self._attempts_lock:
                    self._attempts.pop(job_id, None)
                invocation_handle = InvocationHandle(
                    job_id=job_id, function_id=handle.function_id, version=handle.version,
                )
                self._on_complete(invocation_handle, Err(JobCancelledError(
                    "job was cancelled", context={"function_id": handle.function_id, "job_id": job_id},
                )), [])
                # Anything else queued behind this container is a casualty of
                # the dismissal, not itself cancelled -- same convention
                # _handle_crash/_handle_timeout use for their own drains.
                crash_err = ContainerCrashError(
                    "container dismissed to cancel a sibling job",
                    context={"function_id": handle.function_id},
                )
                for queued_job_id, _scratch_dir, _queued_params in self._drain_job_queue(handle):
                    queued_handle = InvocationHandle(
                        job_id=queued_job_id, function_id=handle.function_id, version=handle.version,
                    )
                    self._on_complete(queued_handle, Err(crash_err), [])
                return True

            job_queue = getattr(handle, "_job_queue", None)
            if job_queue is None:
                continue
            remaining: List[tuple] = []
            found = False
            while True:
                try:
                    item = job_queue.get_nowait()
                except queue.Empty:
                    break
                if item[0] == job_id:
                    found = True
                else:
                    remaining.append(item)
            for item in remaining:
                job_queue.put(item)
            if found:
                self._logger.info_event(
                    Event.Container.JOB_CANCELLED,
                    component=Component.CONTAINER_RUNTIME,
                    function_id=handle.function_id,
                    service_name=handle.service_name,
                    job_id=job_id,
                    status="queued",
                )
                invocation_handle = InvocationHandle(
                    job_id=job_id, function_id=handle.function_id, version=handle.version,
                )
                self._on_complete(invocation_handle, Err(JobCancelledError(
                    "job was cancelled before it started",
                    context={"function_id": handle.function_id, "job_id": job_id},
                )), [])
                return True
        return False

    # ── pump ───────────────────────────────────────────────────────────────────

    def _ensure_pump(self, handle: ContainerHandle) -> None:
        # Keyed by service_name -- unique per pool member, not just per
        # function_id. Keying by function_id alone meant a live pump thread
        # for one version (or one pool member) made _ensure_pump wrongly
        # skip starting a pump for a different handle of the same function
        # (e.g. a newly re-registered version, or another pool member),
        # silently leaving jobs enqueued on it and never pumped.
        with self._pump_threads_lock:
            existing = self._pump_threads.get(handle.service_name)
            if existing and existing.is_alive():
                return
            t = threading.Thread(
                target=self._pump,
                args=(handle,),
                daemon=True,
            )
            self._pump_threads[handle.service_name] = t
            t.start()

    def _open_pump_socket(self, handle: ContainerHandle) -> "tuple[zmq.Socket, threading.Event]":
        """Builds a DEALER socket connected to this handle's container, with
        heartbeating enabled and a background thread watching for the
        resulting EVENT_DISCONNECTED (see _watch_disconnect). Returns the
        socket and an Event that gets set the moment a disconnect is
        observed -- _pump_one_job checks it on every recv timeout."""
        sock = self._zmq_ctx.socket(zmq.DEALER)
        sock.setsockopt(zmq.HEARTBEAT_IVL, _HEARTBEAT_IVL_MS)
        sock.setsockopt(zmq.HEARTBEAT_TIMEOUT, _HEARTBEAT_TIMEOUT_MS)
        sock.setsockopt(zmq.HEARTBEAT_TTL, _HEARTBEAT_TTL_MS)
        sock.setsockopt(zmq.RCVTIMEO, _RECV_POLL_MS)

        disconnected = threading.Event()
        monitor = sock.get_monitor_socket(zmq.EVENT_DISCONNECTED)
        threading.Thread(
            target=self._watch_disconnect, args=(monitor, disconnected), daemon=True,
        ).start()

        sock.connect(handle.zmq_address)
        return sock, disconnected

    @staticmethod
    def _watch_disconnect(monitor: "zmq.Socket", disconnected: threading.Event) -> None:
        """Background thread: waits for the pump socket's EVENT_DISCONNECTED
        (only fires once heartbeating notices the peer stopped responding)
        and flags it, so a genuinely dead container is reported as a crash
        promptly instead of only once/if the job's own max_duration_seconds
        elapses."""
        try:
            while True:
                try:
                    event = recv_monitor_message(monitor)
                except zmq.ZMQError:
                    return
                if event["event"] == zmq.EVENT_DISCONNECTED:
                    disconnected.set()
                    return
        finally:
            monitor.close()

    def _pump(self, handle: ContainerHandle) -> None:
        """One thread per container: sends jobs and receives results."""
        import queue as _queue

        if not hasattr(handle, "_job_queue"):
            handle._job_queue = _queue.Queue()

        sock, disconnected = self._open_pump_socket(handle)

        while handle.status not in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED):
            try:
                job_id, scratch_dir, params = handle._job_queue.get(timeout=1.0)
            except _queue.Empty:
                with handle._lock:
                    if handle.status == ContainerStatus.BUSY:
                        handle.status = ContainerStatus.IDLE
                continue

            inv_handle = InvocationHandle(job_id=job_id, function_id=handle.function_id, version=handle.version)
            if not self._pump_one_job(sock, handle, inv_handle, job_id, scratch_dir, params, disconnected):
                break

            with handle._lock:
                handle.status = ContainerStatus.IDLE

        sock.close()

    def _pump_one_job(
        self,
        sock: "zmq.Socket",
        handle: ContainerHandle,
        inv_handle: InvocationHandle,
        job_id: str,
        scratch_dir: str,
        params: Dict[str, Any],
        disconnected: Optional[threading.Event] = None,
    ) -> bool:
        """Sends one job, then loops replying to any io_requests until the
        container's final result arrives. Returns False if a crash or
        timeout occurred (caller should stop pumping this container).

        disconnected defaults to a fresh, never-set Event for callers that
        don't wire up a real heartbeat monitor (e.g. tests exercising this
        method directly without going through _pump/_open_pump_socket)."""
        if disconnected is None:
            disconnected = threading.Event()

        handle.current_job_id = job_id
        try:
            sock.send_multipart([b"dispatch", job_id.encode(), scratch_dir.encode(), json.dumps(params).encode()])
        except zmq.ZMQError as exc:
            self._handle_crash(handle, inv_handle, str(exc), params)
            return False

        # inv_handle is built by the caller (_pump) before dispatch, so it
        # has no started_at yet -- dataclasses.replace() here (rather than
        # constructing a fresh InvocationHandle) keeps every use of
        # inv_handle below this point -- success, io_request loop, crash --
        # consistently carrying the real dispatch timestamp.
        started_at = time.time()
        inv_handle = dataclasses.replace(inv_handle, started_at=started_at)
        deadline = (
            started_at + handle.max_duration_seconds
            if handle.max_duration_seconds and handle.max_duration_seconds > 0
            else None
        )
        if self._event_bus is not None:
            self._event_bus.emit(BusEvent(
                event_type=JOB_STARTED_EVENT,
                payload={
                    "job_id": job_id, "function_id": handle.function_id,
                    "function_version": handle.version, "params": params,
                },
                timestamp=started_at,
            ))

        while True:
            try:
                frames = sock.recv_multipart()
            except zmq.Again:
                # The socket just went quiet -- on its own that's not
                # evidence of anything wrong (a legitimately slow job looks
                # identical). Only two things turn this into an outcome:
                # heartbeating actually detecting the peer is gone, or this
                # job's own configured duration cap being exceeded.
                if disconnected.is_set():
                    self._handle_crash(handle, inv_handle, "container disconnected (heartbeat timeout)", params)
                    return False
                if deadline is not None and time.time() > deadline:
                    self._handle_timeout(handle, inv_handle, params)
                    return False
                continue
            except zmq.ZMQError as exc:
                self._handle_crash(handle, inv_handle, str(exc), params)
                return False

            if not frames:
                self._handle_crash(handle, inv_handle, "empty frame from container", params)
                return False
            tag = frames[0]

            if tag == b"result":
                if len(frames) != 5:
                    self._handle_crash(handle, inv_handle, "unexpected frame count for result", params)
                    return False
                _, _job_id_b, status_b, payload_b, warnings_b = frames
                status = status_b.decode("utf-8")
                try:
                    result_warnings = json.loads(warnings_b.decode("utf-8"))
                except Exception:
                    result_warnings = []
                with self._attempts_lock:
                    self._attempts.pop(job_id, None)
                handle.current_job_id = None
                if status == "ok":
                    try:
                        value = json.loads(payload_b.decode("utf-8"))
                    except Exception:
                        value = payload_b
                    self._on_complete(inv_handle, Ok(value), result_warnings)
                else:
                    error_msg = payload_b.decode("utf-8", errors="replace")
                    self._on_complete(inv_handle, Err(FunctionRuntimeError(error_msg)), result_warnings)
                return True

            elif tag == b"io_request":
                if len(frames) != 5:
                    self._handle_crash(handle, inv_handle, "unexpected frame count for io_request", params)
                    return False
                _, request_id_b, op_b, ref_json_b, data_b = frames
                op = op_b.decode("utf-8")
                ref = IORef.from_dict(json.loads(ref_json_b.decode("utf-8")))
                result = resolve_io_request(op, ref, data_b or None, self._storage_backends, self._data_registry)
                self._logger.debug_event(
                    Event.DataIO.REQUEST_RECEIVED if result.is_ok else Event.DataIO.REQUEST_FAILED,
                    component=Component.DATAIO,
                    job_id=job_id,
                    op=op,
                    ref_kind=ref.kind,
                )
                reply = [b"io_reply", request_id_b, b"ok", result.unwrap()] if result.is_ok \
                    else [b"io_reply", request_id_b, b"err", str(result.unwrap_err()).encode()]
                try:
                    sock.send_multipart(reply)
                except zmq.ZMQError as exc:
                    self._handle_crash(handle, inv_handle, str(exc), params)
                    return False
                continue

            else:
                self._handle_crash(handle, inv_handle, f"unexpected tag {tag!r} from container", params)
                return False

    def _handle_crash(
        self, handle: ContainerHandle, inv_handle: InvocationHandle, reason: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        if handle.status in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED):
            # cancel() already finalized (and dismissed) this handle -- the
            # pump thread's blocked recv() waking up to a broken connection
            # here is an expected side effect of that dismissal, not a fresh
            # crash. Without this guard, _retry_or_finalize below would see
            # cancel()'s already-cleared _attempts entry as "never tried"
            # and silently re-invoke a job the caller explicitly cancelled.
            return
        with handle._lock:
            handle.status = ContainerStatus.CRASHED
        err = ContainerCrashError(reason, context={"function_id": handle.function_id})
        self._logger.error_event(
            Event.Container.CRASHED,
            component=Component.CONTAINER_RUNTIME,
            function_id=handle.function_id,
            service_name=handle.service_name,
            **err.to_dict(),
        )
        # Remove the real Docker container and free its ledger slot right
        # now, rather than waiting for the next periodic sweep -- otherwise
        # its deterministic name (fn-<function>-v<version>[-p<index>])
        # stays claimed and the next spawn attempt at that slot 409s.
        self._summoner.dismiss(handle, reason="crashed")
        if self._concurrency_client is not None:
            self._concurrency_client.release(handle.function_id, handle.version, handle.pool_index)
        # The in-flight job first, then anything still waiting behind this
        # same container -- both are casualties of the same crash, and both
        # deserve the same retry-or-finalize treatment rather than only the
        # in-flight one getting an outcome and the rest being abandoned.
        self._retry_or_finalize(inv_handle, err, params or {})
        for queued_job_id, _scratch_dir, queued_params in self._drain_job_queue(handle):
            queued_handle = InvocationHandle(
                job_id=queued_job_id, function_id=handle.function_id, version=handle.version,
            )
            self._retry_or_finalize(queued_handle, err, queued_params)

    def _handle_timeout(
        self, handle: ContainerHandle, inv_handle: InvocationHandle,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """A job's own configured max_duration_seconds elapsed with no
        result -- distinct from _handle_crash: the container is presumably
        still alive, just over its allotted time. Still recycles the
        container (same consequence as a crash) since a job that blew its
        deadline may have left it in a stuck state -- dismissed immediately
        below rather than left for the next summon()'s _dismiss_stale() or
        a periodic sweep, so its name is free again right away."""
        if handle.status in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED):
            # Same race as _handle_crash: cancel() already finalized this
            # handle out from under the pump thread's wait.
            return
        with handle._lock:
            handle.status = ContainerStatus.CRASHED
        err = JobTimeoutError(
            f"job exceeded max_duration_seconds={handle.max_duration_seconds}",
            context={"function_id": handle.function_id, "job_id": inv_handle.job_id},
        )
        self._logger.error_event(
            Event.Container.JOB_TIMEOUT,
            component=Component.CONTAINER_RUNTIME,
            function_id=handle.function_id,
            service_name=handle.service_name,
            **err.to_dict(),
        )
        self._summoner.dismiss(handle, reason="timeout")
        if self._concurrency_client is not None:
            self._concurrency_client.release(handle.function_id, handle.version, handle.pool_index)
        self._retry_or_finalize(inv_handle, err, params or {})
        # Anything else queued behind this container is a casualty of the
        # recycle, not a timeout itself (it never got a chance to run) --
        # same convention ProcessFunctionRuntime._handle_timeout already
        # uses (failing them as WorkerCrashedError, not JobTimeoutError).
        crash_err = ContainerCrashError(
            "container recycled after a sibling job's timeout",
            context={"function_id": handle.function_id},
        )
        for queued_job_id, _scratch_dir, queued_params in self._drain_job_queue(handle):
            queued_handle = InvocationHandle(
                job_id=queued_job_id, function_id=handle.function_id, version=handle.version,
            )
            self._retry_or_finalize(queued_handle, crash_err, queued_params)

    def _drain_job_queue(self, handle: ContainerHandle) -> List[tuple]:
        """Empties whatever's left in a dying container's job queue -- jobs
        that were assigned to it but never got to run. Returns a list of
        (job_id, scratch_dir, params) tuples, the same shape _pump() pulls
        off the queue itself."""
        drained: List[tuple] = []
        job_queue = getattr(handle, "_job_queue", None)
        if job_queue is None:
            return drained
        while True:
            try:
                drained.append(job_queue.get_nowait())
            except queue.Empty:
                break
        return drained

    def _max_retries_for(self, function_id: str, version: Optional[int]) -> int:
        """Fails safe to 0 (no retry) whenever the function's current spec
        can't be determined -- e.g. it was deleted mid-flight, or (in tests)
        no registry/spec was wired up at all -- rather than guessing."""
        if self._registry is None:
            return 0
        get_result = self._registry.get(StorageKey(id=function_id, version=version, alias=function_id))
        if get_result.is_err or get_result.unwrap() is None:
            return 0
        spec = get_result.unwrap().runtime_spec
        if spec is None:
            return 0
        return max(0, spec.max_retries)

    def _retry_or_finalize(
        self, inv_handle: InvocationHandle, err: FunctionRuntimeError, params: Dict[str, Any],
    ) -> None:
        """Decides whether a job that just lost its container (crash or
        timeout) gets another attempt or is failed for good. A retried job
        is re-invoked through the exact same placement path (local reuse,
        then leader-driven grow/place) a fresh submission uses -- so it can
        land on a different container, not just get resent to the one that
        just died."""
        job_id = inv_handle.job_id
        max_retries = self._max_retries_for(inv_handle.function_id, inv_handle.version)

        with self._attempts_lock:
            attempts = self._attempts.get(job_id, 0)
            if attempts < max_retries:
                self._attempts[job_id] = attempts + 1
                retry_number = attempts + 1
            else:
                retry_number = None
                self._attempts.pop(job_id, None)

        if retry_number is not None:
            self._logger.info_event(
                Event.Job.RETRY_SCHEDULED,
                component=Component.CONTAINER_RUNTIME,
                job_id=job_id,
                function_id=inv_handle.function_id,
                attempt=retry_number,
                max_retries=max_retries,
                error_message=str(err),
            )
            function_ref = StorageKey(
                id=inv_handle.function_id, version=inv_handle.version, alias=inv_handle.function_id,
            )
            threading.Thread(
                target=self._perform_retry, args=(function_ref, job_id, params), daemon=True,
            ).start()
            return

        self._logger.info_event(
            Event.Job.RETRY_EXHAUSTED,
            component=Component.CONTAINER_RUNTIME,
            job_id=job_id,
            function_id=inv_handle.function_id,
            max_retries=max_retries,
        )
        self._on_complete(inv_handle, Err(err))

    def _perform_retry(self, function_ref: StorageKey, job_id: str, params: Dict[str, Any]) -> None:
        """Runs on its own daemon thread so the crashing container's pump
        thread can finish tearing down instead of blocking on this retry's
        placement (which may itself do Docker/network I/O)."""
        retry_result = self.invoke(function_ref, job_id, params)
        if retry_result.is_err:
            # The retry attempt couldn't even be placed (e.g. the ledger is
            # mid-reconciliation) -- finalize now rather than looping.
            with self._attempts_lock:
                self._attempts.pop(job_id, None)
            err = retry_result.unwrap_err()
            self._logger.info_event(
                Event.Job.RETRY_EXHAUSTED,
                component=Component.CONTAINER_RUNTIME,
                job_id=job_id,
                function_id=function_ref.id,
                error_message=str(err),
            )
            self._on_complete(
                InvocationHandle(job_id=job_id, function_id=function_ref.id, version=function_ref.version),
                Err(err),
            )

    def _alloc_scratch(self, job_id: str) -> str:
        import os
        path = os.path.join(self._config.AXO_ENDPOINT_SCRATCH_ROOT, "containers", job_id)
        os.makedirs(path, exist_ok=True)
        return path
