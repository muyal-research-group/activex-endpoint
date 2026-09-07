from __future__ import annotations

import os
import resource
import uuid
from typing import Any, Dict, Optional

import cloudpickle

from axo_shared.functions.source import materialize_function_from_source

from axo_endpoint.core.dataio import DataIOError, IORef
from axo_endpoint.core.runtime import InvocationContext
from axo_endpoint.dataio import bind_channel, reset_channel

# Sentinel sent down the pipe to tell a worker to stop its receive loop.
SHUTDOWN = None


def apply_rlimits(memory_bytes: int, cpu_seconds: int) -> None:
    """Limits how much memory and CPU time this process is allowed to use."""
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))


class PipeIOChannel:
    """Lets a running function reach back to the endpoint over the same Pipe
    connection used for job dispatch, mid-job, via dataio.read/write."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def request(self, op: str, ref: IORef, data: Optional[bytes]) -> bytes:
        request_id = uuid.uuid4().hex
        try:
            self._conn.send(("io_request", request_id, op, ref, data))
            while True:
                message = self._conn.recv()
                if message[0] == "io_reply" and message[1] == request_id:
                    _, _, status, payload = message
                    break
        except (BrokenPipeError, OSError, EOFError) as exc:
            raise DataIOError(f"dataio channel broken: {exc}") from exc

        if status != "ok":
            raise DataIOError(str(payload))
        return payload


def worker_main(
    conn: Any,
    code_bytes: bytes,
    code_format: str,
    function_name: str,
    memory_limit_bytes: int,
    cpu_limit_seconds: int,
    env_vars: Optional[Dict[str, str]] = None,
) -> None:
    """Runs inside a worker process: loads the function once, then runs it
    again for every new request that arrives, until told to stop.
    env_vars (from the function's RuntimeSpec, as of whichever registration/
    update was current when this worker cold-started) are applied before the
    function code loads, since the function's own top-level code may read
    them at import time -- an update to env_vars only reaches a *new* worker,
    never one already running (lazy effect, no forced recycle)."""
    os.setsid()
    if env_vars:
        os.environ.update(env_vars)
    apply_rlimits(memory_limit_bytes, cpu_limit_seconds)
    if code_format == "source":
        func = materialize_function_from_source(code_bytes, function_name)  # cold start: paid once per worker lifetime
    else:
        func = cloudpickle.loads(code_bytes)  # cold start: paid once per worker lifetime

    while True:
        try:
            message = conn.recv()
        except (EOFError, OSError):
            break
        if message is SHUTDOWN:
            break

        # message is always ("dispatch", job_id, scratch_dir, params) by protocol invariant
        _, job_id, scratch_dir, params = message
        ctx = InvocationContext(job_id=job_id, scratch_dir=scratch_dir)
        token = bind_channel(PipeIOChannel(conn))
        try:
            value = func(params, ctx)
            # 4th element is ctx.warnings, accumulated via ctx.warn() during
            # the call above -- carried even on success so a function that
            # warns but still returns cleanly doesn't lose them.
            conn.send(("result", "ok", value, ctx.warnings))
        except Exception as exc:  # noqa: BLE001 - report it, don't crash the worker for a user bug
            conn.send(("result", "err", repr(exc), ctx.warnings))
        finally:
            reset_channel(token)

    conn.close()
