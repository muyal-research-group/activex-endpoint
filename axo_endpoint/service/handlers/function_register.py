from __future__ import annotations

import time
from typing import Callable, Union

from axo_endpoint.core.errors import MissingFieldError, StorageFailureError
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.network.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log

_Logger = Union[Log, DumbLogger]


class FunctionRegisterHandler(CommandHandler):
    """Registers a function's code and metadata."""

    def __init__(
        self,
        registry: FunctionRegistry,
        now_fn: Callable[[], float] = time.time,
        logger: _Logger = None,
    ) -> None:
        self._registry = registry
        self._now_fn = now_fn
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        """Reads the function's name, version, and code from the request, and saves them."""
        t0 = time.monotonic()
        name = command.envelope.get("name")
        version = command.envelope.get("version")

        if not name or version is None:
            err = MissingFieldError(
                "name and version are required",
                context={"fields": ["name", "version"]},
            )
            self._logger.info_event(
                "FUNCTION.REGISTERED",
                component="handler.function_register",
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        result = self._registry.register(name=name, version=version, code=command.payload, now=self._now_fn())
        if result.is_err:
            raw = result.unwrap_err()
            err = StorageFailureError(str(raw), context={"function_name": name, "version": version})
            self._logger.info_event(
                "FUNCTION.REGISTERED",
                component="handler.function_register",
                status="error",
                function_name=name,
                function_version=version,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        key = result.unwrap()
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            "FUNCTION.REGISTERED",
            component="handler.function_register",
            status="ok",
            function_name=name,
            function_version=version,
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, metadata={"function_id": key.id, "version": key.version})
