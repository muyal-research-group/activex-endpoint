from __future__ import annotations

import time
from typing import Callable, Union

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.errors import MissingFieldError, StorageFailureError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class DataDeleteHandler(CommandHandler):
    """Removes a registered data record's metadata and chunk bytes from this
    node. Always leader-gated (via LeaderProxyHandler, like DATA_REGISTER) --
    a catalog mutation, so it must go through the same
    DirtyTracker/STATE_SYNC_PUSH replication path as registration, this time
    tombstoning the key on every follower instead of adding one (see
    DataRegistrySyncBridge.on_data_deleted)."""

    def __init__(
        self, registry: DataRegistry, now_fn: Callable[[], float] = time.time, logger: _Logger = None,
    ) -> None:
        self._registry = registry
        self._now_fn = now_fn
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        t0 = time.monotonic()
        envelope = command.envelope
        name = envelope.get("name")
        version = envelope.get("version")

        if not name or version is None:
            err = MissingFieldError("name and version are required", context={"fields": ["name", "version"]})
            self._logger.info_event(
                Event.Data.DELETED,
                component=Component.HANDLER_DATA_DELETE,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        result = self._registry.delete(name, version, now=self._now_fn())
        if result.is_err:
            raw = result.unwrap_err()
            err = StorageFailureError(str(raw), context={"data_name": name, "version": version})
            self._logger.info_event(
                Event.Data.DELETED,
                component=Component.HANDLER_DATA_DELETE,
                status="error",
                data_name=name,
                data_version=version,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            Event.Data.DELETED,
            component=Component.HANDLER_DATA_DELETE,
            status="ok",
            data_name=name,
            data_version=version,
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, metadata={"data_id": name, "version": version})
