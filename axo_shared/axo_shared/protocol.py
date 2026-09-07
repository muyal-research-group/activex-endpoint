from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from axo_shared.errors import AxoError


@dataclass(frozen=True)
class Command:
    """One incoming request: which operation it is, its data, and any extra bytes."""

    operation: str
    content_type: str
    envelope: Dict[str, Any]
    payload: bytes = b""


@dataclass(frozen=True)
class CommandResult:
    """The outcome of handling one command: success or failure, plus the result or error."""

    ok: bool
    payload: bytes = b""
    error: str = ""
    error_code: int = 0
    error_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_error(err: "AxoError", metadata: Dict[str, Any] | None = None) -> "CommandResult":
        """Creates a failed result from an AxoError, copying its code, name, and message."""
        return CommandResult(
            ok=False,
            error=err.message,
            error_code=err.code,
            error_name=err.name,
            metadata=metadata or {},
        )


class CommandHandler(ABC):
    """Something that can handle one command and produce a result."""

    @abstractmethod
    def handle(self, command: Command) -> CommandResult:
        """Handles one command and returns the result."""


class CommandDispatcher(ABC):
    """Something that accepts a command for processing and returns the result."""

    @abstractmethod
    def submit(self, command: Command) -> CommandResult:
        """Submits a command to be processed and returns its result."""
