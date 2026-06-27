from __future__ import annotations

import os
import resource
from typing import Any

import cloudpickle

from axo_endpoint.core.runtime import InvocationContext

# Sentinel sent down the pipe to tell a worker to stop its receive loop.
SHUTDOWN = None


def apply_rlimits(memory_bytes: int, cpu_seconds: int) -> None:
    """Limits how much memory and CPU time this process is allowed to use."""
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))


def worker_main(conn: Any, code_bytes: bytes, memory_limit_bytes: int, cpu_limit_seconds: int) -> None:
    """Runs inside a worker process: loads the function once, then runs it
    again for every new request that arrives, until told to stop."""
    os.setsid()
    apply_rlimits(memory_limit_bytes, cpu_limit_seconds)
    func = cloudpickle.loads(code_bytes)  # cold start: paid once per worker lifetime

    while True:
        try:
            message = conn.recv()
        except (EOFError, OSError):
            break
        if message is SHUTDOWN:
            break

        job_id, scratch_dir, params = message
        ctx = InvocationContext(job_id=job_id, scratch_dir=scratch_dir)
        try:
            value = func(params, ctx)
            conn.send(("ok", value))
        except Exception as exc:  # noqa: BLE001 - report it, don't crash the worker for a user bug
            conn.send(("err", repr(exc)))

    conn.close()
