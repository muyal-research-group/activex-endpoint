from __future__ import annotations

from typing import Any, Dict, Union

from option import Result

from axo_endpoint.core.errors import InvocationError
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.runtime.base import FunctionRuntime, FunctionRuntimeError, InvocationHandle
from axo_endpoint.core.storage.backend import StorageKey
from axo_endpoint.log import DumbLogger, Log

_Logger = Union[Log, DumbLogger]


class RuntimeDispatcher(FunctionRuntime):
    """Routes invoke() calls to the process runtime or the container runtime
    based on the RuntimeSpec stored with each function."""

    def __init__(
        self,
        registry: FunctionRegistry,
        process_runtime: FunctionRuntime,
        container_runtime: FunctionRuntime,
        logger: _Logger = None,
    ) -> None:
        self._registry = registry
        self._process = process_runtime
        self._container = container_runtime
        self._logger: _Logger = logger or DumbLogger()

    def invoke(
        self,
        function_ref: StorageKey,
        job_id: str,
        params: Dict[str, Any],
    ) -> Result[InvocationHandle, FunctionRuntimeError]:
        get_result = self._registry.get(function_ref)
        if get_result.is_err or get_result.unwrap() is None:
            from option import Err
            return Err(InvocationError(
                f"function {function_ref.id!r} not found",
                context={"function_id": function_ref.id},
            ))

        record = get_result.unwrap()
        spec = record.runtime_spec
        if spec and spec.type == "container":
            return self._container.invoke(function_ref, job_id, params)
        return self._process.invoke(function_ref, job_id, params)

    def cancel(self, job_id: str) -> bool:
        """job_id alone doesn't say which runtime a job landed on -- try
        both. A job is only ever tracked by one of them, so at most one
        call actually finds and cancels anything."""
        process_cancelled = self._process.cancel(job_id)
        container_cancelled = self._container.cancel(job_id)
        return process_cancelled or container_cancelled
