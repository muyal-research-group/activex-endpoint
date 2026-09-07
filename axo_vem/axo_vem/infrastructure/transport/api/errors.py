from __future__ import annotations

from typing import Optional, Union

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from axo_vem.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    NotOwnerError,
    UpstreamTimeoutError,
)
from axo_vem.log import DumbLogger, Log
from axo_vem.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


def register_exception_handlers(app: FastAPI, logger: Optional[_Logger] = None) -> None:
    """Translates domain errors raised by application use cases into the
    exact HTTP status codes/detail bodies the old inline
    `raise HTTPException(status_code=..., detail=...)` calls in api/routes/*.py
    used to produce -- centralizing what were previously 4+ duplicated
    inline ownership/existence checks (see migration plan decision E).
    Registered most-specific-first; DomainError is the catch-all fallback
    (maps to 500) for anything not covered by a more specific subclass, e.g.
    application/identity/signup.py's local-persist-failure path.

    Also the single place every domain-error failure across every entity/
    route gets logged with a classified code + description -- error_code is
    just the raised exception's class name (already a stable, meaningful
    identifier here, see domain/errors.py), so no separate mapping table is
    needed."""
    _logger: _Logger = logger or DumbLogger()

    def _log(exc: DomainError, status_code: int) -> None:
        _logger.warning_event(
            Event.Http.REQUEST_FAILED,
            component=Component.HTTP,
            error_code=exc.__class__.__name__,
            description=str(exc),
            status_code=status_code,
        )

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        _log(exc, 404)
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(NotOwnerError)
    async def _not_owner(request: Request, exc: NotOwnerError) -> JSONResponse:
        _log(exc, 403)
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def _conflict(request: Request, exc: ConflictError) -> JSONResponse:
        _log(exc, 409)
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(UpstreamTimeoutError)
    async def _upstream_timeout(request: Request, exc: UpstreamTimeoutError) -> JSONResponse:
        _log(exc, 504)
        return JSONResponse(status_code=504, content={"detail": str(exc)})

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        _log(exc, 500)
        return JSONResponse(status_code=500, content={"detail": str(exc)})
