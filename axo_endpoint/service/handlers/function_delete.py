from __future__ import annotations

import time
from typing import Callable, Optional, Union

from axo_shared.activity.models import FUNCTION_DELETE_FAILED_EVENT
from axo_endpoint.core.errors import MissingFieldError, StorageFailureError
from axo_endpoint.core.events.bus import Event as BusEvent, EventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.storage.backend import StorageKey
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class FunctionDeleteHandler(CommandHandler):
    """Removes a registered function's code and metadata."""

    def __init__(
        self,
        registry: FunctionRegistry,
        now_fn: Callable[[], float] = time.time,
        event_bus: Optional[EventBus] = None,
        logger: _Logger = None,
    ) -> None:
        self._registry = registry
        self._now_fn = now_fn
        self._event_bus = event_bus
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        """Reads the function's id and version from the request, and deletes it."""
        t0 = time.monotonic()
        function_id = command.envelope.get("function_id")
        version = command.envelope.get("version")

        if not function_id or version is None:
            err = MissingFieldError(
                "function_id and version are required",
                context={"fields": ["function_id", "version"]},
            )
            self._logger.info_event(
                Event.Function.DELETED,
                component=Component.HANDLER_FUNCTION_DELETE,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        key = StorageKey(id=function_id, version=version, alias=function_id)
        result = self._registry.delete(key, now=self._now_fn())
        if result.is_err:
            raw = result.unwrap_err()
            err = StorageFailureError(str(raw), context={"function_id": function_id, "version": version})
            self._logger.info_event(
                Event.Function.DELETED,
                component=Component.HANDLER_FUNCTION_DELETE,
                status="error",
                function_id=function_id,
                function_version=version,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            if self._event_bus is not None:
                self._event_bus.emit(BusEvent(
                    event_type=FUNCTION_DELETE_FAILED_EVENT,
                    payload={
                        "function_id": function_id, "version": version,
                        "failure": {
                            "error_class": err.name, "error_code": err.code,
                            "component": "function_registry", "message": err.message,
                            "traceback": None, "is_transient": False,
                        },
                    },
                    timestamp=self._now_fn(),
                ))
            return CommandResult.from_error(err)

        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            Event.Function.DELETED,
            component=Component.HANDLER_FUNCTION_DELETE,
            status="ok",
            function_id=function_id,
            function_version=version,
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, metadata={"function_id": key.id, "version": key.version})
