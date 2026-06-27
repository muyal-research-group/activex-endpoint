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


# ── 1xxx: client / validation ─────────────────────────────────────────────────

class MissingFieldError(AxoError):
    code = 1001
    name = "MISSING_FIELD"


class InvalidFieldError(AxoError):
    code = 1002
    name = "INVALID_FIELD"


class UnknownOperationError(AxoError):
    code = 1003
    name = "UNKNOWN_OPERATION"


# ── 2xxx: not found / state ───────────────────────────────────────────────────

class FunctionNotFoundError(AxoError):
    code = 2001
    name = "FUNCTION_NOT_FOUND"


class JobNotFoundError(AxoError):
    code = 2002
    name = "JOB_NOT_FOUND"


class InvalidStateError(AxoError):
    code = 2003
    name = "INVALID_STATE_TRANSITION"


# ── 3xxx: runtime / execution ─────────────────────────────────────────────────

class WorkerCrashedError(AxoError):
    code = 3001
    name = "WORKER_CRASHED"


class FunctionExecError(AxoError):
    code = 3002
    name = "FUNCTION_EXEC_FAILED"


class InvocationError(AxoError):
    code = 3003
    name = "INVOCATION_FAILED"


# ── 4xxx: infrastructure ──────────────────────────────────────────────────────

class QueueFullError(AxoError):
    code = 4001
    name = "QUEUE_FULL"


class DispatcherClosedError(AxoError):
    code = 4002
    name = "DISPATCHER_CLOSED"


class StorageFailureError(AxoError):
    code = 4003
    name = "STORAGE_ERROR"


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
