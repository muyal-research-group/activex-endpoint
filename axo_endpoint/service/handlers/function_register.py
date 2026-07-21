from __future__ import annotations

import time
from typing import Callable, Optional, Union

from axo_shared.activity.models import FUNCTION_REGISTER_FAILED_EVENT
from axo_endpoint.core.errors import MissingFieldError, StorageFailureError
from axo_endpoint.core.events.bus import Event as BusEvent, EventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.functions.params_schema import parse_params_schema
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_shared.runtime.spec import RuntimeSpec
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class FunctionRegisterHandler(CommandHandler):
    """Registers a function's code and metadata."""

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
        """Reads the function's id, name, and code from the request, and
        saves them -- version is never read from the request, the registry
        assigns it."""
        t0 = time.monotonic()
        function_id = command.envelope.get("function_id")
        name = command.envelope.get("name")

        if not function_id or not name:
            err = MissingFieldError(
                "function_id and name are required",
                context={"fields": ["function_id", "name"]},
            )
            self._logger.info_event(
                Event.Function.REGISTERED,
                component=Component.HANDLER_FUNCTION_REGISTER,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        runtime_spec: RuntimeSpec | None = None
        raw_spec = command.envelope.get("runtime_spec")
        if raw_spec is not None:
            runtime_spec = RuntimeSpec.from_dict(raw_spec)
        code_format = command.envelope.get("code_format", "cloudpickle")
        params_schema = parse_params_schema(command.envelope.get("params_schema")) or None

        result = self._registry.register(
            function_id=function_id,
            name=name,
            code=command.payload,
            now=self._now_fn(),
            runtime_spec=runtime_spec,
            code_format=code_format,
            params_schema=params_schema,
        )
        if result.is_err:
            raw = result.unwrap_err()
            err = StorageFailureError(str(raw), context={"function_id": function_id, "function_name": name})
            self._logger.info_event(
                Event.Function.REGISTERED,
                component=Component.HANDLER_FUNCTION_REGISTER,
                status="error",
                function_id=function_id,
                function_name=name,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            if self._event_bus is not None:
                self._event_bus.emit(BusEvent(
                    event_type=FUNCTION_REGISTER_FAILED_EVENT,
                    payload={
                        # No real version was ever assigned -- never fabricate
                        # one (see ExternalEventForwardingBridge._log_version_unknown).
                        "function_id": function_id, "version": None,
                        "failure": {
                            "error_class": err.name, "error_code": err.code,
                            "component": "function_registry", "message": err.message,
                            "traceback": None, "is_transient": False,
                        },
                    },
                    timestamp=self._now_fn(),
                ))
            return CommandResult.from_error(err)

        key = result.unwrap()
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            Event.Function.REGISTERED,
            component=Component.HANDLER_FUNCTION_REGISTER,
            status="ok",
            function_id=function_id,
            function_name=name,
            function_version=key.version,
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, metadata={"function_id": key.id, "version": key.version})
