from __future__ import annotations

import time
from typing import Union

from axo_endpoint.core.errors import FunctionNotFoundError, MissingFieldError
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.core.storage.backend import StorageKey
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class ContainerBootstrapHandler(CommandHandler):
    """Returns the function code and requirements to a container that just started up."""

    def __init__(self, registry: FunctionRegistry, logger: _Logger = None) -> None:
        self._registry = registry
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        t0 = time.monotonic()
        function_id = command.envelope.get("function_id")
        version = command.envelope.get("version")

        if not function_id or version is None:
            err = MissingFieldError(
                "function_id and version are required",
                context={"fields": ["function_id", "version"]},
            )
            self._logger.warning_event(
                Event.Container.BOOTSTRAP_REQUESTED,
                component=Component.HANDLER_CONTAINER_BOOTSTRAP,
                status="error",
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        self._logger.debug_event(
            Event.Container.BOOTSTRAP_REQUESTED,
            component=Component.HANDLER_CONTAINER_BOOTSTRAP,
            function_id=function_id,
            version=version,
        )

        key = StorageKey(id=function_id, version=int(version))
        get_result = self._registry.get(key)
        if get_result.is_err or get_result.unwrap() is None:
            err = FunctionNotFoundError(
                f"function {function_id!r} v{version} not registered",
                context={"function_id": function_id, "version": version},
            )
            self._logger.warning_event(
                Event.Container.BOOTSTRAP_REQUESTED,
                component=Component.HANDLER_CONTAINER_BOOTSTRAP,
                status="error",
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        record = get_result.unwrap()
        requirements = []
        if record.runtime_spec:
            requirements = list(record.runtime_spec.requirements)

        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            Event.Container.BOOTSTRAP_COMPLETE,
            component=Component.HANDLER_CONTAINER_BOOTSTRAP,
            status="ok",
            function_id=function_id,
            version=version,
            requirements_count=len(requirements),
            duration_ms=duration_ms,
        )
        return CommandResult(
            ok=True,
            payload=record.code,
            metadata={"requirements": requirements, "code_format": record.code_format, "name": record.name},
        )
