from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

from option import Result

from axo_endpoint.core.errors import AxoError
from axo_endpoint.core.storage.backend import StorageKey


class FunctionRuntimeError(AxoError):
    """Base class for all FunctionRuntime failure modes."""

    code = 3000
    name = "RUNTIME_ERROR"


@dataclass(frozen=True)
class InvocationHandle:
    """Confirms that a job was accepted for execution."""

    job_id: str
    function_id: str


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
