from __future__ import annotations

import time
from typing import Callable, Union

from fastapi import FastAPI, Request

from axo_vem.log import DumbLogger, Log
from axo_vem.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


def register_logging_middleware(app: FastAPI, logger: _Logger) -> None:
    """One INFO log per HTTP request (method, path, status_code,
    duration_ms) -- covers every entity reachable over HTTP (signup,
    profile, virtual environments, node lifecycle, buckets, jobs, ...) in
    one place, without threading a logger through each individual use
    case. Failure detail (error_code/description) is logged separately by
    infrastructure/transport/api/errors.py's exception handlers, which run
    before this middleware sees the response."""

    @app.middleware("http")
    async def _log_requests(request: Request, call_next: Callable):
        t0 = time.monotonic()
        response = await call_next(request)
        logger.info_event(
            Event.Http.REQUEST_HANDLED,
            component=Component.HTTP,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.monotonic() - t0) * 1000, 2),
        )
        return response
