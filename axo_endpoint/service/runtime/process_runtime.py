from __future__ import annotations

import multiprocessing
import os
import queue
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from option import Err, Ok, Result

from axo_shared.activity.models import (
    FUNCTION_CRASHED_EVENT,
    FUNCTION_DEPLOYED_EVENT,
    FUNCTION_DEPLOY_FAILED_EVENT,
    FUNCTION_STOPPED_EVENT,
    JOB_STARTED_EVENT,
)
from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.dataio import resolve_io_request
from axo_endpoint.core.storage.backend import StorageBackend
from axo_endpoint.core.errors import FunctionNotFoundError, JobTimeoutError, WorkerCrashedError
from axo_endpoint.core.events.bus import Event as BusEvent, EventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.runtime import FunctionRuntime, FunctionRuntimeError, InvocationHandle
from axo_endpoint.core.storage.backend import StorageKey
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event
from axo_endpoint.service.runtime.scratch import allocate_scratch_dir, cleanup_scratch_dir
from axo_endpoint.service.runtime.worker_entry import worker_main

_Logger = Union[Log, DumbLogger]

OnComplete = Callable[[InvocationHandle, "Result[Any, FunctionRuntimeError]"], None]

# How often _pump polls the worker pipe rather than blocking indefinitely on
# recv() -- short enough that a job's own max_duration_seconds deadline (if
# configured) gets checked promptly instead of only once per job.
_POLL_INTERVAL_SECONDS = 1.0


class WorkerHandle:
    """Tracks one worker process: how it's being used, and how to talk to it."""

    def __init__(
        self,
        function_id: str,
        version: Optional[int] = None,
        process: Optional[Any] = None,
        conn: Optional[Any] = None,
        request_queue: Optional["queue.Queue[Any]"] = None,
        max_duration_seconds: float = 0,
    ) -> None:
        self.function_id = function_id
        self.version = version
        self.process = process
        self.conn = conn
        self.request_queue = request_queue if request_queue is not None else queue.Queue()
        self.pump_thread: Optional[threading.Thread] = None
        self.last_used: float = 0.0
        self.invocation_count: int = 0
        # True while this worker is currently running a function call.
        self.busy: bool = False
        # Stashed from RuntimeSpec.max_duration_seconds at spawn time (a
        # per-(function, version) constant). 0 = unlimited, same convention
        # as the spec.
        self.max_duration_seconds = max_duration_seconds

    def touch(self, now: float) -> None:
        """Records that this worker was just used."""
        self.last_used = now
        self.invocation_count += 1

    def is_idle(self, ttl_seconds: float, now: float) -> bool:
        """Checks whether this worker has been unused for too long."""
        return not self.busy and now - self.last_used > ttl_seconds

    def exceeded_max_invocations(self, max_invocations: int) -> bool:
        """Checks whether this worker has handled too many calls and should be recycled."""
        if max_invocations == 0:  # 0 = unlimited, matches Config's default
            return False
        return self.invocation_count >= max_invocations


class WorkerRegistry:
    """Keeps track of all worker handles, pooled per (function, version) --
    keying by function id alone would let a worker spawned for an older
    version silently keep serving jobs submitted against a newly
    re-registered version of the same function, since invoke() would find
    and reuse that stale-version handle without ever comparing versions.

    Each (function, version) may have more than one live worker at once, up
    to that function's configured RuntimeSpec.max_concurrency -- callers
    pick a specific handle out of the pool (get_idle_or_none/least_loaded)
    rather than the registry handing back "the" worker for a key."""

    def __init__(self) -> None:
        self._workers: Dict[Tuple[str, Optional[int]], List[WorkerHandle]] = {}

    def pool(self, function_id: str, version: Optional[int]) -> List[WorkerHandle]:
        """Every live worker currently handling this (function, version), if any."""
        return list(self._workers.get((function_id, version), []))

    def get_idle_or_none(self, function_id: str, version: Optional[int]) -> Optional[WorkerHandle]:
        """The first genuinely-available worker in this (function, version)'s
        pool, if any -- both not currently running a job AND with nothing
        already queued behind it. handle.busy only flips True once the
        worker's pump thread actually dequeues an item, which can lag a
        burst of invoke() calls on the caller's thread; checking the queue
        too avoids piling several jobs onto one worker before the pool ever
        gets a chance to grow."""
        for handle in self._workers.get((function_id, version), []):
            if not handle.busy and handle.request_queue.empty():
                return handle
        return None

    def least_loaded(self, function_id: str, version: Optional[int]) -> Optional[WorkerHandle]:
        """The pool member with the shortest pending-job queue -- used when
        the pool is already at capacity and none are idle, so a new job
        still has to land somewhere (each worker's own pump thread already
        processes its queue serially, so this is "wait for capacity" for
        free rather than a real scheduling decision)."""
        pool = self._workers.get((function_id, version), [])
        if not pool:
            return None
        return min(pool, key=lambda handle: handle.request_queue.qsize())

    def register(self, handle: WorkerHandle) -> None:
        """Adds a worker handle to its (function, version) pool."""
        self._workers.setdefault((handle.function_id, handle.version), []).append(handle)

    def evict(self, handle: WorkerHandle) -> None:
        """Removes one specific worker handle from its pool, cleaning up the
        key entirely once its pool is empty. A no-op if the handle isn't
        tracked (already evicted)."""
        key = (handle.function_id, handle.version)
        pool = self._workers.get(key)
        if pool is None:
            return
        try:
            pool.remove(handle)
        except ValueError:
            return
        if not pool:
            del self._workers[key]

    def list_handles(self) -> List[WorkerHandle]:
        """Lists all worker handles currently tracked, across every pool."""
        return [handle for pool in self._workers.values() for handle in pool]

    def sweep_idle(self, ttl_seconds: float, now: float) -> List[str]:
        """Removes workers that have been unused for too long, and returns their function ids."""
        idle = [handle for handle in self.list_handles() if handle.is_idle(ttl_seconds, now)]
        for handle in idle:
            self.evict(handle)
        return [handle.function_id for handle in idle]

    def sweep_max_invocations(self, max_invocations: int) -> List[str]:
        """Removes workers that have handled too many calls, and returns their function ids."""
        exceeded = [handle for handle in self.list_handles() if handle.exceeded_max_invocations(max_invocations)]
        for handle in exceeded:
            self.evict(handle)
        return [handle.function_id for handle in exceeded]


class ProcessFunctionRuntime(FunctionRuntime):
    """Runs functions by giving each one its own process.

    Accepting a job and finishing a job happen at different times —
    invoke() returns right away, and the result arrives later.
    """

    def __init__(
        self,
        function_registry: FunctionRegistry,
        on_complete: OnComplete,
        scratch_root: str = "/tmp/axo_endpoint/scratch",
        memory_limit_bytes: int = 512 * 1024 * 1024,
        cpu_limit_seconds: int = 30,
        storage_backends: Optional[Dict[str, StorageBackend]] = None,
        data_registry: Optional[DataRegistry] = None,
        event_bus: Optional[EventBus] = None,
        logger: _Logger = None,
    ) -> None:
        self._function_registry  = function_registry
        self._on_complete        = on_complete
        self._scratch_root       = scratch_root
        self._memory_limit_bytes = memory_limit_bytes
        self._cpu_limit_seconds  = cpu_limit_seconds
        self._storage_backends   = storage_backends or {}
        self._data_registry      = data_registry
        self._event_bus          = event_bus
        self._workers            = WorkerRegistry()
        self._spawn_lock         = threading.Lock()
        self._logger: _Logger    = logger or DumbLogger()

    def invoke(
        self, function_ref: StorageKey, job_id: str, params: Dict[str, Any]
    ) -> Result[InvocationHandle, FunctionRuntimeError]:
        """Starts running a function and returns right away, before it finishes.
        Dispatches to an idle worker in the function's pool if one exists;
        grows the pool (up to RuntimeSpec.max_concurrency) if there's room;
        otherwise queues behind whichever pool member is least busy."""
        handle = self._workers.get_idle_or_none(function_ref.id, function_ref.version)
        if handle is None:
            with self._spawn_lock:
                handle = self._workers.get_idle_or_none(function_ref.id, function_ref.version)  # re-check post-lock
                if handle is None:
                    pool_size = len(self._workers.pool(function_ref.id, function_ref.version))
                    if pool_size < self._max_concurrency_for(function_ref):
                        spawn_result = self._spawn_worker(function_ref)
                        if spawn_result.is_err:
                            return Err(spawn_result.unwrap_err())
                        handle = spawn_result.unwrap()
                    else:
                        handle = self._workers.least_loaded(function_ref.id, function_ref.version)

        if handle is None:
            # Pool was reported non-empty but every member vanished (e.g. all
            # crashed) between the size check and here -- spawn fresh rather
            # than fail the job outright.
            spawn_result = self._spawn_worker(function_ref)
            if spawn_result.is_err:
                return Err(spawn_result.unwrap_err())
            handle = spawn_result.unwrap()

        handle.request_queue.put((job_id, params))
        self._logger.debug_event(
            Event.Runtime.JOB_INVOKED,
            component=Component.RUNTIME,
            function_id=function_ref.id,
            job_id=job_id,
            params_keys=list(params.keys()),
        )
        return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id, version=function_ref.version))

    def _max_concurrency_for(self, function_ref: StorageKey) -> int:
        """Looks up the function's configured RuntimeSpec.max_concurrency,
        defaulting to 1 (today's serial behavior) if the function or its
        spec can't be found. invoke()'s own registry lookup happens again
        inside _spawn_worker when a new worker is actually needed; this one
        is just for the pool-capacity check and is cheap against the
        in-memory backend."""
        record_result = self._function_registry.get(function_ref)
        if record_result.is_err:
            return 1
        record = record_result.unwrap()
        if record is None or record.runtime_spec is None:
            return 1
        return max(1, record.runtime_spec.max_concurrency)

    def _spawn_worker(self, function_ref: StorageKey) -> Result[WorkerHandle, FunctionRuntimeError]:
        """Starts a new worker process for a function and begins pumping requests to it."""
        record_result = self._function_registry.get(function_ref)
        if record_result.is_err:
            err = FunctionRuntimeError(str(record_result.unwrap_err()))
            self._emit_deploy_failed(function_ref, err)
            return Err(err)
        record = record_result.unwrap()
        if record is None:
            err = FunctionNotFoundError(
                f"no registered function for {function_ref}",
                context={"function_id": function_ref.id, "version": function_ref.version},
            )
            self._emit_deploy_failed(function_ref, err)
            return Err(err)

        env_vars = record.runtime_spec.env_vars if record.runtime_spec else None
        parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
        process = multiprocessing.get_context("fork").Process(
            target=worker_main,
            args=(
                child_conn, record.code, record.code_format, record.name,
                self._memory_limit_bytes, self._cpu_limit_seconds, env_vars,
            ),
            daemon=True,
        )
        process.start()
        child_conn.close()  # parent only needs its own end

        handle = WorkerHandle(
            function_id=function_ref.id, version=function_ref.version,
            process=process, conn=parent_conn, request_queue=queue.Queue(),
            max_duration_seconds=record.runtime_spec.max_duration_seconds if record.runtime_spec else 0,
        )
        self._workers.register(handle)
        self._logger.debug_event(
            Event.Runtime.WORKER_SPAWNED,
            component=Component.RUNTIME,
            function_id=function_ref.id,
            pid=process.pid,
        )

        pump_thread = threading.Thread(target=self._pump, args=(handle,), daemon=True)
        handle.pump_thread = pump_thread
        pump_thread.start()

        if self._event_bus is not None:
            self._event_bus.emit(BusEvent(
                event_type=FUNCTION_DEPLOYED_EVENT,
                payload={"function_id": function_ref.id, "version": function_ref.version},
                timestamp=time.time(),
            ))

        return Ok(handle)

    def _emit_deploy_failed(self, function_ref: StorageKey, err: FunctionRuntimeError) -> None:
        if self._event_bus is None:
            return
        self._event_bus.emit(BusEvent(
            event_type=FUNCTION_DEPLOY_FAILED_EVENT,
            payload={
                "function_id": function_ref.id, "version": function_ref.version,
                "error_message": err.message or str(err),
            },
            timestamp=time.time(),
        ))

    def sweep_idle(self, ttl_seconds: float, now: float) -> List[str]:
        """Stops and removes workers that have been unused for too long."""
        return self._sweep(lambda handle: handle.is_idle(ttl_seconds, now), reason="idle_ttl")

    def sweep_max_invocations(self, max_invocations: int) -> List[str]:
        """Stops and removes workers that have handled too many calls."""
        return self._sweep(lambda handle: handle.exceeded_max_invocations(max_invocations), reason="max_invocations")

    def _sweep(self, predicate: Callable[[WorkerHandle], bool], reason: str = "unknown") -> List[str]:
        """Stops and removes every worker matching the given condition."""
        evicted = []
        evicted_handles = []
        for handle in self._workers.list_handles():
            if predicate(handle):
                self._workers.evict(handle)
                self._kill_worker(handle)
                evicted.append(handle.function_id)
                evicted_handles.append(handle)
        if evicted:
            self._logger.debug_event(
                Event.Runtime.WORKER_REAPED,
                component=Component.RUNTIME,
                evicted=evicted,
                reason=reason,
            )
            if self._event_bus is not None:
                now = time.time()
                for handle in evicted_handles:
                    self._event_bus.emit(BusEvent(
                        event_type=FUNCTION_STOPPED_EVENT,
                        payload={"function_id": handle.function_id, "version": handle.version, "reason": reason},
                        timestamp=now,
                    ))
        return evicted

    def _kill_worker(self, handle: WorkerHandle) -> None:
        """Stops the worker process and anything it started."""
        self._terminate_process(handle)
        if handle.request_queue is not None:
            handle.request_queue.put(None)

    @staticmethod
    def _terminate_process(handle: WorkerHandle) -> None:
        if handle.process is not None:
            try:
                pgid = os.getpgid(handle.process.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

    def _pump(self, handle: WorkerHandle) -> None:
        """Sends each waiting request to the worker, one at a time, and reports back its result."""
        while True:
            item = handle.request_queue.get()
            if item is None:  # shutdown sentinel from _kill_worker
                break
            job_id, params = item

            handle.busy = True
            scratch_dir = allocate_scratch_dir(self._scratch_root, job_id)
            t_start = None
            try:
                try:
                    handle.conn.send(("dispatch", job_id, scratch_dir, params))
                except (BrokenPipeError, OSError):
                    self._handle_crash(handle, job_id, t_start)
                    return

                t_start = time.time()
                if self._event_bus is not None:
                    self._event_bus.emit(BusEvent(
                        event_type=JOB_STARTED_EVENT,
                        payload={
                            "job_id": job_id, "function_id": handle.function_id,
                            "function_version": handle.version, "params": params,
                        },
                        timestamp=t_start,
                    ))

                deadline = (
                    t_start + handle.max_duration_seconds
                    if handle.max_duration_seconds and handle.max_duration_seconds > 0
                    else None
                )
                status = payload = None
                while True:
                    # poll() (rather than a blocking recv()) so a configured
                    # max_duration_seconds deadline gets checked regularly
                    # instead of only once the worker finally replies. A
                    # dead worker's pipe closing is still detected promptly
                    # either way -- poll() returns True as soon as EOF is
                    # pending, and the recv() below then raises.
                    if not handle.conn.poll(timeout=_POLL_INTERVAL_SECONDS):
                        if deadline is not None and time.time() > deadline:
                            self._handle_timeout(handle, job_id, t_start)
                            return
                        continue
                    try:
                        message = handle.conn.recv()
                    except (EOFError, OSError):
                        self._handle_crash(handle, job_id, t_start)
                        return

                    kind = message[0]
                    if kind == "result":
                        _, status, payload = message
                        break
                    elif kind == "io_request":
                        _, request_id, op, ref, io_data = message
                        result = resolve_io_request(op, ref, io_data, self._storage_backends, self._data_registry)
                        self._logger.debug_event(
                            Event.DataIO.REQUEST_RECEIVED if result.is_ok else Event.DataIO.REQUEST_FAILED,
                            component=Component.DATAIO,
                            job_id=job_id,
                            op=op,
                            ref_kind=ref.kind,
                        )
                        reply = ("io_reply", request_id, "ok", result.unwrap()) if result.is_ok \
                            else ("io_reply", request_id, "err", str(result.unwrap_err()))
                        try:
                            handle.conn.send(reply)
                        except (BrokenPipeError, OSError):
                            self._handle_crash(handle, job_id, t_start)
                            return
                        continue

                handle.touch(time.time())
                invocation_handle = InvocationHandle(
                    job_id=job_id, function_id=handle.function_id, version=handle.version, started_at=t_start,
                )
                if status == "ok":
                    self._on_complete(invocation_handle, Ok(payload))
                else:
                    self._on_complete(invocation_handle, Err(FunctionRuntimeError(payload)))
            finally:
                cleanup_scratch_dir(scratch_dir)
                handle.busy = False

        try:
            handle.conn.close()
        except OSError:
            pass

    def _handle_crash(
        self, handle: WorkerHandle, in_flight_job_id: str, in_flight_started_at: Optional[float] = None,
    ) -> None:
        """Marks a worker's jobs as failed and removes it after the worker process dies unexpectedly.
        Only the in-flight job (if any) has a real started_at -- jobs still
        sitting in the queue were never dispatched, so they get None."""
        self._workers.evict(handle)

        failed_jobs = [(in_flight_job_id, in_flight_started_at)]
        while True:
            try:
                pending_job_id, _params = handle.request_queue.get_nowait()
            except queue.Empty:
                break
            failed_jobs.append((pending_job_id, None))

        self._logger.debug_event(
            Event.Runtime.WORKER_CRASHED,
            component=Component.RUNTIME,
            function_id=handle.function_id,
            failed_job_count=len(failed_jobs),
        )
        if self._event_bus is not None:
            self._event_bus.emit(BusEvent(
                event_type=FUNCTION_CRASHED_EVENT,
                payload={"function_id": handle.function_id, "version": handle.version},
                timestamp=time.time(),
            ))
        for job_id, started_at in failed_jobs:
            invocation_handle = InvocationHandle(
                job_id=job_id, function_id=handle.function_id, version=handle.version, started_at=started_at,
            )
            self._on_complete(invocation_handle, Err(WorkerCrashedError(
                "worker crashed",
                context={"function_id": handle.function_id, "job_id": job_id},
            )))

    def _handle_timeout(
        self, handle: WorkerHandle, in_flight_job_id: str, in_flight_started_at: Optional[float] = None,
    ) -> None:
        """A job's own configured max_duration_seconds elapsed with no
        result -- distinct from _handle_crash: the worker process is
        presumably still alive, just stuck, so (unlike a crash) it's
        actually terminated here rather than assumed already dead. Recycles
        the worker the same as a crash would; only the in-flight job gets
        JobTimeoutError -- any others still queued behind it are casualties
        of the recycle, not timeouts themselves, so they're failed as
        WorkerCrashedError (mirrors _handle_crash's own draining loop)."""
        self._workers.evict(handle)

        pending_jobs = []
        while True:
            try:
                pending_job_id, _params = handle.request_queue.get_nowait()
            except queue.Empty:
                break
            pending_jobs.append(pending_job_id)

        self._terminate_process(handle)

        self._logger.debug_event(
            Event.Runtime.WORKER_JOB_TIMEOUT,
            component=Component.RUNTIME,
            function_id=handle.function_id,
            job_id=in_flight_job_id,
            max_duration_seconds=handle.max_duration_seconds,
        )
        if self._event_bus is not None:
            self._event_bus.emit(BusEvent(
                event_type=FUNCTION_CRASHED_EVENT,
                payload={"function_id": handle.function_id, "version": handle.version},
                timestamp=time.time(),
            ))

        in_flight_handle = InvocationHandle(
            job_id=in_flight_job_id, function_id=handle.function_id,
            version=handle.version, started_at=in_flight_started_at,
        )
        self._on_complete(in_flight_handle, Err(JobTimeoutError(
            f"job exceeded max_duration_seconds={handle.max_duration_seconds}",
            context={"function_id": handle.function_id, "job_id": in_flight_job_id},
        )))
        for job_id in pending_jobs:
            invocation_handle = InvocationHandle(
                job_id=job_id, function_id=handle.function_id, version=handle.version,
            )
            self._on_complete(invocation_handle, Err(WorkerCrashedError(
                "worker recycled after a sibling job timed out",
                context={"function_id": handle.function_id, "job_id": job_id},
            )))
