from __future__ import annotations

import time
from typing import Callable, Optional, Union

from axo_endpoint.core.data import BucketRegistry, DataRegistry
from axo_endpoint.core.errors import BucketNotFoundError, MissingFieldError, QuotaExceededError, StorageFailureError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]


class DataRegisterHandler(CommandHandler):
    """Declares the metadata for a piece of data ahead of the actual bytes --
    chunk_bytes arrive separately via DATA_CHUNK_PUT (client push) or a
    function's dataio.write_chunks (stream write). Always leader-gated (via
    LeaderProxyHandler, like FUNCTION_REGISTER): the response's
    ``leader_rpc_uri`` is exactly the address the caller should send
    DATA_CHUNK_PUT/DATA_STATUS to next -- those two ops are deliberately not
    leader-proxied, so the caller must target the leader directly.

    If ``bucket_registry`` is given and ``name`` is namespaced as
    "{bucket}/{key}", registration is quota-gated against that bucket's
    declared quota_bytes -- rejected before the DataRecord is ever created.
    Unnamespaced names (no "/") skip this check entirely, so existing
    non-bucket DATA_REGISTER callers are unaffected."""

    def __init__(
        self,
        registry: DataRegistry,
        own_rpc_uri: str,
        now_fn: Callable[[], float] = time.time,
        logger: _Logger = None,
        bucket_registry: Optional[BucketRegistry] = None,
    ) -> None:
        self._registry = registry
        self._own_rpc_uri = own_rpc_uri
        self._now_fn = now_fn
        self._logger: _Logger = logger or DumbLogger()
        self._bucket_registry = bucket_registry

    def handle(self, command: Command) -> CommandResult:
        """Reads the data's name, version, format, kind, total_size, chunk_bytes
        (and optional content_hash) from the request, and registers them."""
        t0 = time.monotonic()
        envelope = command.envelope
        name = envelope.get("name")
        version = envelope.get("version")
        total_size = envelope.get("total_size")
        chunk_bytes = envelope.get("chunk_bytes")
        format_ = envelope.get("format", "raw")
        kind = envelope.get("kind", "fs")
        content_hash = envelope.get("content_hash")
        content_hash_algo = envelope.get("content_hash_algo", "sha256")

        if not name or version is None or total_size is None or not chunk_bytes:
            err = MissingFieldError(
                "name, version, total_size, and chunk_bytes are required",
                context={"fields": ["name", "version", "total_size", "chunk_bytes"]},
            )
            self._logger.info_event(
                Event.Data.REGISTERED,
                component=Component.HANDLER_DATA_REGISTER,
                status="error",
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        if self._bucket_registry is not None and "/" in name:
            quota_err = self._check_bucket_quota(name, total_size)
            if quota_err is not None:
                self._logger.info_event(
                    Event.Data.REGISTERED,
                    component=Component.HANDLER_DATA_REGISTER,
                    status="error",
                    data_name=name,
                    data_version=version,
                    duration_ms=round((time.monotonic() - t0) * 1000, 2),
                    **quota_err.to_dict(),
                )
                return CommandResult.from_error(quota_err)

        result = self._registry.register(
            name=name,
            version=version,
            format=format_,
            kind=kind,
            total_size=total_size,
            chunk_bytes=chunk_bytes,
            now=self._now_fn(),
            content_hash=content_hash,
            content_hash_algo=content_hash_algo,
        )
        if result.is_err:
            raw = result.unwrap_err()
            err = StorageFailureError(str(raw), context={"data_name": name, "version": version})
            self._logger.info_event(
                Event.Data.REGISTERED,
                component=Component.HANDLER_DATA_REGISTER,
                status="error",
                data_name=name,
                data_version=version,
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        record = result.unwrap()
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        self._logger.info_event(
            Event.Data.REGISTERED,
            component=Component.HANDLER_DATA_REGISTER,
            status="ok",
            data_name=name,
            data_version=version,
            duration_ms=duration_ms,
        )
        return CommandResult(ok=True, metadata={
            "data_id": name,
            "version": version,
            "kind": record.kind,
            "format": record.format,
            "total_size": record.total_size,
            "chunk_bytes": record.chunk_bytes,
            "total_chunks": record.total_chunks,
            "leader_rpc_uri": self._own_rpc_uri,
        })

    def _check_bucket_quota(self, name: str, total_size: int) -> Union[BucketNotFoundError, QuotaExceededError, None]:
        """Validates a namespaced "{bucket}/{key}" DATA_REGISTER against its
        bucket's declared quota_bytes, ahead of creating the DataRecord.
        Sums existing DataRecords already in that bucket (by name prefix) +
        this new registration's total_size -- lives here rather than inside
        DataRegistry/BucketRegistry themselves, keeping those two decoupled
        from each other (matches how DataRegistry has zero knowledge of
        FunctionRegistry today)."""
        bucket_name = name.split("/", 1)[0]
        bucket_result = self._bucket_registry.get(bucket_name)
        bucket = bucket_result.unwrap() if bucket_result.is_ok else None
        if bucket is None:
            return BucketNotFoundError(f"bucket '{bucket_name}' does not exist", context={"bucket": bucket_name})

        prefix = f"{bucket_name}/"
        used = sum(r.total_size for r in self._registry.list_records() if r.name.startswith(prefix))
        if used + total_size > bucket.quota_bytes:
            return QuotaExceededError(
                f"registering {total_size} bytes into bucket '{bucket_name}' would exceed its quota "
                f"({used} used of {bucket.quota_bytes})",
                context={
                    "bucket": bucket_name, "used_bytes": used,
                    "additional_bytes": total_size, "quota_bytes": bucket.quota_bytes,
                },
            )
        return None
