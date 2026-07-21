from __future__ import annotations

import contextvars
import dataclasses
import json
from typing import Any, Iterable, Iterator, Optional, Protocol

from axo_endpoint.core.dataio import (
    APPEND_CHUNK,
    CHUNK_STATUS,
    FINALIZE_STREAM,
    OPEN_STREAM,
    READ_CHUNK,
    DataIOUnavailableError,
    IORef,
    get_format,
)

DEFAULT_CHUNK_BYTES = 262144


class IOChannel(Protocol):
    """Whatever transport is carrying this job (Pipe or ZMQ) implements this --
    a single blocking round trip to the endpoint and back."""

    def request(self, op: str, ref: IORef, data: Optional[bytes]) -> bytes: ...


_channel_var: "contextvars.ContextVar[Optional[IOChannel]]" = contextvars.ContextVar(
    "axo_endpoint_dataio_channel", default=None
)


def bind_channel(channel: IOChannel) -> contextvars.Token:
    """Called by the worker/container entrypoint right before invoking the
    function, so dataio.read/write below know how to reach the endpoint."""
    return _channel_var.set(channel)


def reset_channel(token: contextvars.Token) -> None:
    _channel_var.reset(token)


def _require_channel() -> IOChannel:
    channel = _channel_var.get()
    if channel is None:
        raise DataIOUnavailableError(
            "dataio.read/write called with no active job io channel bound "
            "(e.g. calling it outside a running job, or from an invocation "
            "path with no endpoint round trip available)"
        )
    return channel


def read(ref: IORef) -> Any:
    """Fetches ``ref`` from the endpoint's storage and deserializes it per ``ref.format``."""
    channel = _require_channel()
    raw = channel.request("read", ref, None)
    return get_format(ref.format).unwrap().decode(raw)


def write(obj: Any, ref: IORef) -> None:
    """Serializes ``obj`` per ``ref.format`` and stores it at ``ref`` via the endpoint."""
    channel = _require_channel()
    data = get_format(ref.format).unwrap().encode(obj)
    channel.request("write", ref, data)


def iter_chunks(ref: IORef) -> Iterator[bytes]:
    """Reads registered data chunk by chunk -- bounded memory throughout,
    since the endpoint never materializes the whole blob for this call and
    neither does this generator. Yields raw bytes per chunk (ref.format
    deserialization only applies to the whole reconstructed object, via
    read() -- a function consuming chunks decides for itself how to process
    each one)."""
    channel = _require_channel()
    status_raw = channel.request(CHUNK_STATUS, ref, None)
    total_chunks = json.loads(status_raw.decode("utf-8"))["total_chunks"]
    for i in range(total_chunks):
        yield channel.request(READ_CHUNK, dataclasses.replace(ref, chunk_index=i), None)


def write_chunks(
    name: str,
    version: int,
    chunks: Iterable[bytes],
    format: str = "raw",
    kind: str = "fs",
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> IORef:
    """Streams a function's output in chunks without needing its total size
    upfront: open_stream once, append_chunk per item, finalize_stream once --
    registering the result exactly like a client upload (replicated,
    inspectable via DATA_STATUS/DATA_INFO) as soon as it finalizes. Distinct
    from write(), which stores one ad-hoc unregistered blob and stays
    available for outputs that don't need registration/replication."""
    channel = _require_channel()
    location = f"{name}/{version}"
    ref = IORef(kind=kind, location=location, format=format)
    channel.request(OPEN_STREAM, ref, json.dumps({"chunk_bytes": chunk_bytes}).encode("utf-8"))
    for chunk in chunks:
        channel.request(APPEND_CHUNK, ref, chunk)
    channel.request(FINALIZE_STREAM, ref, None)
    return ref
