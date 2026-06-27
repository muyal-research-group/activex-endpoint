from __future__ import annotations

import json
from typing import Any, Dict, List

from option import Err, Ok, Result

from axo_endpoint.core.errors import (
    AxoError,
    MalformedEnvelopeError,
    MalformedFrameCountError,
    MalformedMetadataError,
)
from axo_endpoint.core.network.protocol import Command, CommandResult

# Names of the operations a client can request.
PING              = "PING"
FUNCTION_REGISTER = "FUNCTION_REGISTER"
JOB_SUBMIT        = "JOB_SUBMIT"
JOB_RESULT        = "JOB_RESULT"
METRICS           = "METRICS"


class WireError(AxoError):
    """Malformed frames -- wrong count, or a body that doesn't decode."""

    code = 5000
    name = "WIRE_ERROR"


def encode_command(command: Command) -> List[bytes]:
    """Turns a Command into the byte frames sent over the wire."""
    return [
        command.operation.encode("utf-8"),
        command.content_type.encode("utf-8"),
        json.dumps(command.envelope).encode("utf-8"),
        command.payload,
    ]


def decode_command(frames: List[bytes]) -> Result[Command, AxoError]:
    """Rebuilds a Command from the byte frames received over the wire."""
    if len(frames) != 4:
        return Err(MalformedFrameCountError(
            f"expected 4 frames, got {len(frames)}",
            context={"frame_count": len(frames)},
        ))

    operation_b, content_type_b, envelope_b, payload = frames
    try:
        envelope = json.loads(envelope_b.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Err(MalformedEnvelopeError(str(exc)))

    return Ok(
        Command(
            operation=operation_b.decode("utf-8"),
            content_type=content_type_b.decode("utf-8"),
            envelope=envelope,
            payload=payload,
        )
    )


def encode_command_result(result: CommandResult) -> List[bytes]:
    """Turns a CommandResult into the byte frames sent back over the wire."""
    meta: Dict[str, Any] = dict(result.metadata)
    if result.error_code:
        meta["error_code"] = result.error_code
        meta["error_name"] = result.error_name
    return [
        b"1" if result.ok else b"0",
        result.error.encode("utf-8"),
        json.dumps(meta, default=str).encode("utf-8"),
        result.payload,
    ]


def decode_command_result(frames: List[bytes]) -> Result[CommandResult, AxoError]:
    """Rebuilds a CommandResult from the byte frames received over the wire."""
    if len(frames) != 4:
        return Err(MalformedFrameCountError(
            f"expected 4 frames, got {len(frames)}",
            context={"frame_count": len(frames)},
        ))

    ok_b, error_b, metadata_b, payload = frames
    try:
        metadata = json.loads(metadata_b.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Err(MalformedMetadataError(str(exc)))

    return Ok(
        CommandResult(ok=ok_b == b"1", error=error_b.decode("utf-8"), metadata=metadata, payload=payload)
    )
