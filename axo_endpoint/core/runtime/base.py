from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

from option import Result

from axo_endpoint.core.errors import AxoError
from axo_endpoint.core.storage.backend import StorageKey


class FunctionRuntimeError(AxoError):
    """Base class for all FunctionRuntime failure modes."""

    code = 3000
    name = "RUNTIME_ERROR"


@dataclass(frozen=True)
class InvocationHandle:
    """Confirms that a job was accepted for execution. version/started_at
    are None on the "accepted" handle invoke() returns and on any handle
    built before a job was ever actually dispatched to a worker/container
    (e.g. a cold-start readiness timeout, or a job still queued behind a
    crashed worker) -- both are only meaningfully populated once dispatch
    has actually happened, so downstream consumers (build_completion_recorder)
    must treat them as optional."""

    job_id: str
    function_id: str
    version: Optional[int] = None
    started_at: Optional[float] = None


@dataclass(frozen=True)
class InvocationContext:
    """Information given to a running function: its job id and a folder for temporary files."""

    job_id: str
    scratch_dir: str


class FunctionRuntime(ABC):
    """Something that can run a registered function with the given parameters."""

    @abstractmethod
    def invoke(
        self, function_ref: StorageKey, job_id: str, params: Dict[str, Any]
    ) -> Result[InvocationHandle, FunctionRuntimeError]:
        """Starts running a function and returns right away, before it finishes."""
