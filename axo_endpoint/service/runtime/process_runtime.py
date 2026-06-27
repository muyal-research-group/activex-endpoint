from __future__ import annotations

import multiprocessing
import os
import queue
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Union

from option import Err, Ok, Result

from axo_endpoint.core.errors import FunctionNotFoundError, WorkerCrashedError
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.runtime import FunctionRuntime, FunctionRuntimeError, InvocationHandle
from axo_endpoint.core.storage.backend import StorageKey
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.service.runtime.scratch import allocate_scratch_dir, cleanup_scratch_dir
from axo_endpoint.service.runtime.worker_entry import worker_main

_Logger = Union[Log, DumbLogger]

OnComplete = Callable[[InvocationHandle, "Result[Any, FunctionRuntimeError]"], None]


class WorkerHandle:
    """Tracks one worker process: how it's being used, and how to talk to it."""

    def __init__(
        self,
        function_id: str,
        process: Optional[Any] = None,
        conn: Optional[Any] = None,
        request_queue: Optional["queue.Queue[Any]"] = None,
    ) -> None:
        self.function_id = function_id
        self.process = process
        self.conn = conn
        self.request_queue = request_queue
        self.pump_thread: Optional[threading.Thread] = None
        self.last_used: float = 0.0
        self.invocation_count: int = 0
        # True while this worker is currently running a function call.
        self.busy: bool = False

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
    """Keeps track of all worker handles, one per function."""

    def __init__(self) -> None:
        self._workers: Dict[str, WorkerHandle] = {}

    def get_or_none(self, function_id: str) -> Optional[WorkerHandle]:
        """Looks up the worker handle for a function, if one exists."""
        return self._workers.get(function_id)

    def register(self, handle: WorkerHandle) -> None:
        """Adds a worker handle to the registry."""
        self._workers[handle.function_id] = handle

    def evict(self, function_id: str) -> Optional[WorkerHandle]:
        """Removes and returns a worker handle from the registry."""
        return self._workers.pop(function_id, None)

    def list_handles(self) -> List[WorkerHandle]:
        """Lists all worker handles currently tracked."""
        return list(self._workers.values())

    def sweep_idle(self, ttl_seconds: float, now: float) -> List[str]:
        """Removes workers that have been unused for too long, and returns their function ids."""
        idle_ids = [
            function_id
            for function_id, handle in self._workers.items()
            if handle.is_idle(ttl_seconds, now)
        ]
        for function_id in idle_ids:
            self.evict(function_id)
        return idle_ids

    def sweep_max_invocations(self, max_invocations: int) -> List[str]:
        """Removes workers that have handled too many calls, and returns their function ids."""
        exceeded_ids = [
            function_id
            for function_id, handle in self._workers.items()
            if handle.exceeded_max_invocations(max_invocations)
        ]
        for function_id in exceeded_ids:
            self.evict(function_id)
        return exceeded_ids


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
        logger: _Logger = None,
    ) -> None:
        self._function_registry  = function_registry
        self._on_complete        = on_complete
        self._scratch_root       = scratch_root
        self._memory_limit_bytes = memory_limit_bytes
        self._cpu_limit_seconds  = cpu_limit_seconds
        self._workers            = WorkerRegistry()
        self._spawn_lock         = threading.Lock()
        self._logger: _Logger    = logger or DumbLogger()

    def invoke(
        self, function_ref: StorageKey, job_id: str, params: Dict[str, Any]
    ) -> Result[InvocationHandle, FunctionRuntimeError]:
        """Starts running a function and returns right away, before it finishes."""
        handle = self._workers.get_or_none(function_ref.id)
        if handle is None:
            with self._spawn_lock:
                handle = self._workers.get_or_none(function_ref.id)  # re-check post-lock
                if handle is None:
                    spawn_result = self._spawn_worker(function_ref)
                    if spawn_result.is_err:
                        return Err(spawn_result.unwrap_err())
                    handle = spawn_result.unwrap()

        handle.request_queue.put((job_id, params))
        self._logger.debug_event(
            "RUNTIME.JOB_INVOKED",
            component="runtime",
            function_id=function_ref.id,
            job_id=job_id,
        )
        return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id))

    def _spawn_worker(self, function_ref: StorageKey) -> Result[WorkerHandle, FunctionRuntimeError]:
        """Starts a new worker process for a function and begins pumping requests to it."""
        record_result = self._function_registry.get(function_ref)
        if record_result.is_err:
            return Err(FunctionRuntimeError(str(record_result.unwrap_err())))
        record = record_result.unwrap()
        if record is None:
            return Err(FunctionNotFoundError(
                f"no registered function for {function_ref}",
                context={"function_id": function_ref.id, "version": function_ref.version},
            ))

        parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
        process = multiprocessing.get_context("fork").Process(
            target=worker_main,
            args=(child_conn, record.code, self._memory_limit_bytes, self._cpu_limit_seconds),
            daemon=True,
        )
        process.start()
        child_conn.close()  # parent only needs its own end

        handle = WorkerHandle(
            function_id=function_ref.id, process=process, conn=parent_conn, request_queue=queue.Queue()
        )
        self._workers.register(handle)
        self._logger.debug_event(
            "RUNTIME.WORKER_SPAWNED",
            component="runtime",
            function_id=function_ref.id,
        )

        pump_thread = threading.Thread(target=self._pump, args=(handle,), daemon=True)
        handle.pump_thread = pump_thread
        pump_thread.start()

        return Ok(handle)

    def sweep_idle(self, ttl_seconds: float, now: float) -> List[str]:
        """Stops and removes workers that have been unused for too long."""
        return self._sweep(lambda handle: handle.is_idle(ttl_seconds, now))

    def sweep_max_invocations(self, max_invocations: int) -> List[str]:
        """Stops and removes workers that have handled too many calls."""
        return self._sweep(lambda handle: handle.exceeded_max_invocations(max_invocations))

    def _sweep(self, predicate: Callable[[WorkerHandle], bool]) -> List[str]:
        """Stops and removes every worker matching the given condition."""
        evicted = []
        for handle in self._workers.list_handles():
            if predicate(handle):
                self._workers.evict(handle.function_id)
                self._kill_worker(handle)
                evicted.append(handle.function_id)
        if evicted:
            self._logger.debug_event(
                "RUNTIME.WORKER_REAPED",
                component="runtime",
                evicted=evicted,
            )
        return evicted

    def _kill_worker(self, handle: WorkerHandle) -> None:
        """Stops the worker process and anything it started."""
        if handle.process is not None:
            try:
                pgid = os.getpgid(handle.process.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
        if handle.request_queue is not None:
            handle.request_queue.put(None)

    def _pump(self, handle: WorkerHandle) -> None:
        """Sends each waiting request to the worker, one at a time, and reports back its result."""
        while True:
            item = handle.request_queue.get()
            if item is None:  # shutdown sentinel from _kill_worker
                break
            job_id, params = item

            handle.busy = True
            scratch_dir = allocate_scratch_dir(self._scratch_root, job_id)
            try:
                try:
                    handle.conn.send((job_id, scratch_dir, params))
                except (BrokenPipeError, OSError):
                    self._handle_crash(handle, job_id)
                    return

                try:
                    status, payload = handle.conn.recv()
                except (EOFError, OSError):
                    self._handle_crash(handle, job_id)
                    return

                handle.touch(time.time())
                invocation_handle = InvocationHandle(job_id=job_id, function_id=handle.function_id)
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

    def _handle_crash(self, handle: WorkerHandle, in_flight_job_id: str) -> None:
        """Marks a worker's jobs as failed and removes it after the worker process dies unexpectedly."""
        self._workers.evict(handle.function_id)

        failed_job_ids = [in_flight_job_id]
        while True:
            try:
                pending_job_id, _params = handle.request_queue.get_nowait()
            except queue.Empty:
                break
            failed_job_ids.append(pending_job_id)

        self._logger.debug_event(
            "RUNTIME.WORKER_CRASHED",
            component="runtime",
            function_id=handle.function_id,
            failed_job_count=len(failed_job_ids),
        )
        for job_id in failed_job_ids:
            invocation_handle = InvocationHandle(job_id=job_id, function_id=handle.function_id)
            self._on_complete(invocation_handle, Err(WorkerCrashedError(
                "worker crashed",
                context={"function_id": handle.function_id, "job_id": job_id},
            )))
