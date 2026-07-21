from __future__ import annotations

from typing import Any, Dict, List, Optional

from axo_shared import wire
from axo_shared.functions.identity import compute_function_id
from axo_shared.protocol import Command

from axo_vem.domain.compute.repository import EndpointRepository
from axo_vem.domain.errors import ConflictError, NotFoundError, UpstreamTimeoutError
from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository
from axo_vem.infrastructure.transport.zmq_command.endpoint_client import resolve_rpc_uri, send_command


class RegisterFunctionUseCase:
    """Replaces the body of the former POST /endpoints/{endpoint_id}/functions
    route handler. The caller no longer picks an endpoint -- they pick a
    virtual_environment_id (a resource they actually understand and own),
    and this use case auto-resolves the single, most-recently-active
    endpoint currently assigned to that VE to route the FUNCTION_REGISTER
    command to. This also fixes the underlying bug where virtual_environment_id
    used to be derived implicitly from whichever endpoint the caller
    happened to click (see delete_function.py's docstring for the failure
    mode that caused)."""

    def __init__(
        self,
        virtual_environment_repository: VirtualEnvironmentRepository,
        endpoint_repository: EndpointRepository,
        command_timeout_seconds: float = 3.0,
    ) -> None:
        self._virtual_environment_repository = virtual_environment_repository
        self._endpoint_repository = endpoint_repository
        self._command_timeout_seconds = command_timeout_seconds

    def execute(
        self,
        *,
        virtual_environment_id: str,
        current_user_id: str,
        name: str,
        code: bytes,
        runtime_spec: Optional[Dict[str, Any]] = None,
        params_schema: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        virtual_environment = self._virtual_environment_repository.get(virtual_environment_id)
        if virtual_environment is None:
            raise NotFoundError("virtual environment not found")
        virtual_environment.assert_owner(current_user_id)

        endpoints = self._endpoint_repository.list_by_virtual_environment(virtual_environment_id)
        if not endpoints:
            raise ConflictError("no endpoint assigned to this virtual environment")
        endpoint = endpoints[0]
        if not endpoint.router_bind:
            raise ConflictError(f"endpoint {endpoint.endpoint_id} has no known router_bind")
        rpc_uri = resolve_rpc_uri(endpoint.router_bind, endpoint.endpoint_id)

        function_id = compute_function_id(current_user_id, virtual_environment_id, name)

        envelope: Dict[str, Any] = {"function_id": function_id, "name": name, "code_format": "source"}
        if runtime_spec is not None:
            envelope["runtime_spec"] = runtime_spec
        if params_schema:
            envelope["params_schema"] = params_schema

        command = Command(
            operation=wire.FUNCTION_REGISTER,
            content_type="application/octet-stream",
            envelope=envelope,
            payload=code,
        )
        result = send_command(rpc_uri, command, self._command_timeout_seconds)
        if result.is_err:
            raise UpstreamTimeoutError(str(result.unwrap_err()))

        command_result = result.unwrap()
        if not command_result.ok:
            raise ConflictError(command_result.error)
        return {"endpoint_id": endpoint.endpoint_id, "name": name, **(command_result.metadata or {})}
