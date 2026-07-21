from __future__ import annotations

import time
from typing import Callable, Union

from axo_endpoint.core.errors import MissingFieldError, StorageFailureError
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.storage.backend import StorageKey
from axo_shared.functions.params_schema import parse_params_schema
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class FunctionUpdateHandler(CommandHandler):
    """In-place mutation of an existing function version's params_schema/
    env_vars -- no new version created, no code touched. Takes effect
    lazily on whatever worker/container next naturally redeploys."""

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
        """Reads function_id, version, and the fields to merge from the
        request, and applies the update."""
        t0 = time.monotonic()
        function_id = command.envelope.get("function_id")
        version = command.envelope.get("version")

        if not function_id or version is None:
            err = MissingFieldError(
                "function_id and version are required",
                context={"fields": ["function_id", "version"]},
            )
            self._logger.info_event(
                Event.Function.UPDATED,
                component=Component.HANDLER_FUNCTION_UPDATE,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        params_schema = parse_params_schema(command.envelope.get("params_schema")) or None
        env_vars = command.envelope.get("env_vars") or None

        key = StorageKey(id=function_id, version=version, alias=function_id)
        result = self._registry.update(
            key, now=self._now_fn(), params_schema=params_schema, env_vars=env_vars,
        )
        if result.is_err:
            raw = result.unwrap_err()
            err = StorageFailureError(str(raw), context={"function_id": function_id, "version": version})
            self._logger.info_event(
                Event.Function.UPDATED,
                component=Component.HANDLER_FUNCTION_UPDATE,
                status="error",
                function_id=function_id,
                function_version=version,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            Event.Function.UPDATED,
            component=Component.HANDLER_FUNCTION_UPDATE,
            status="ok",
            function_id=function_id,
            function_version=version,
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, metadata={"function_id": function_id, "version": version})
