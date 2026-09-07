from __future__ import annotations

import inspect
from typing import Any, Dict, Optional


class AxoError(Exception):
    """Base class for all endpoint-level failures.

    Subclasses set ``code`` and ``name`` as class-level attributes.
    Source location (module, function, line) is captured automatically at
    the call site — one frame up from wherever ``AxoError(...)`` is called.
    """

    code: int = 0
    name: str = "AXO_ERROR"

    def __init__(self, message: str = "", context: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.context: Dict[str, Any] = context if context is not None else {}
        frame = inspect.stack()[1]
        module_file = frame.filename.rsplit("/", 1)[-1]
        self.src_module = module_file[:-3] if module_file.endswith(".py") else module_file
        self.src_fn = frame.function
        self.src_line = frame.lineno

    def to_dict(self) -> Dict[str, Any]:
        """Returns all error fields as a flat dict ready to spread into a log event."""
        d: Dict[str, Any] = {
            "error_code": self.code,
            "error_name": self.name,
            "error_message": self.message,
        }
        if self.context:
            d["error_context"] = self.context
        return d


# ── 5xxx: transport / wire ────────────────────────────────────────────────────

class MalformedFrameCountError(AxoError):
    code = 5001
    name = "MALFORMED_FRAME_COUNT"


class MalformedEnvelopeError(AxoError):
    code = 5002
    name = "MALFORMED_ENVELOPE"


class MalformedMetadataError(AxoError):
    code = 5003
    name = "MALFORMED_METADATA"


class MalformedEventEnvelopeError(AxoError):
    code = 5004
    name = "MALFORMED_EVENT_ENVELOPE"
