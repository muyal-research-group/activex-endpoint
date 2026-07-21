from __future__ import annotations

import time
from typing import Callable, Union

from axo_endpoint.core.data import BucketRegistry
from axo_endpoint.core.errors import BucketAlreadyExistsError, MissingFieldError, StorageFailureError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class BucketRegisterHandler(CommandHandler):
    """Declares a named, quota-enforced bucket ahead of any data being
    registered into it. Structurally identical to DataRegisterHandler --
    leader-gated (via LeaderProxyHandler, like FUNCTION_REGISTER/DATA_REGISTER),
    metadata-only, no chunk bytes involved."""

    def __init__(
        self,
        registry: BucketRegistry,
        now_fn: Callable[[], float] = time.time,
        logger: _Logger = None,
    ) -> None:
        self._registry = registry
        self._now_fn = now_fn
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        t0 = time.monotonic()
        envelope = command.envelope
        name = envelope.get("name")
        quota_bytes = envelope.get("quota_bytes")

        if not name or quota_bytes is None:
            err = MissingFieldError(
                "name and quota_bytes are required",
                context={"fields": ["name", "quota_bytes"]},
            )
            self._logger.info_event(
                Event.Bucket.REGISTERED,
                component=Component.HANDLER_BUCKET_REGISTER,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        result = self._registry.register(name=name, quota_bytes=quota_bytes, now=self._now_fn())
        if result.is_err:
            raw = result.unwrap_err()
            # BucketRegistry.register can fail with either a genuine backend
            # StorageError or its own BucketAlreadyExistsError -- the latter
            # should surface as-is rather than getting relabeled
            # STORAGE_FAILURE.
            err = raw if isinstance(raw, BucketAlreadyExistsError) else StorageFailureError(
                str(raw), context={"bucket_name": name},
            )
            self._logger.info_event(
                Event.Bucket.REGISTERED,
                component=Component.HANDLER_BUCKET_REGISTER,
                status="error",
                bucket_name=name,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        bucket = result.unwrap()
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            Event.Bucket.REGISTERED,
            component=Component.HANDLER_BUCKET_REGISTER,
            status="ok",
            bucket_name=name,
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, metadata={
            "name": bucket.name,
            "quota_bytes": bucket.quota_bytes,
            "created_at": bucket.created_at,
        })
