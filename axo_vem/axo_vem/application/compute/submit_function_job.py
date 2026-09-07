from __future__ import annotations

from typing import Any, Dict

from axo_shared import wire
from axo_shared.protocol import Command

from axo_vem.domain.compute.repository import EndpointRepository, FunctionRepository
from axo_vem.domain.errors import ConflictError, NotFoundError, UpstreamTimeoutError
from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository
from axo_vem.infrastructure.transport.zmq_command.endpoint_client import resolve_rpc_uri, send_command


class SubmitFunctionJobUseCase:
    """Resolves a target endpoint for a JOB_SUBMIT entirely server-side, so
    a caller only ever needs to know a function_id/version -- never an
    endpoint_id (mirrors RegisterFunctionUseCase's own "caller picks a VE,
    not a node" rationale). Preferred target is the function's VE's
    currently-elected mesh leader (VirtualEnvironment.leader_endpoint_id,
    kept live by application/projector/compute_handler.py's handling of
    LeaderElected/ConsensusViewChanged) if it's still actually a member of
    that VE; otherwise falls back to the same "most-recently-seen VE
    endpoint" pick RegisterFunctionUseCase already trusts.
    """

    def __init__(
        self,
        function_repository: FunctionRepository,
        virtual_environment_repository: VirtualEnvironmentRepository,
        endpoint_repository: EndpointRepository,
        command_timeout_seconds: float = 3.0,
    ) -> None:
        self._function_repository = function_repository
        self._virtual_environment_repository = virtual_environment_repository
        self._endpoint_repository = endpoint_repository
        self._command_timeout_seconds = command_timeout_seconds

    def execute(self, *, function_id: str, version: int, params: Dict[str, Any]) -> Dict[str, Any]:
        function = self._function_repository.get(function_id, version)
        if function is None or function.deleted_at is not None:
            raise NotFoundError("function not found")
        if function.virtual_environment_id is None:
            raise ConflictError("function is not assigned to a virtual environment")
        ve_id = function.virtual_environment_id

        endpoint_id = self._resolve_endpoint_id(ve_id)
        endpoint = self._endpoint_repository.get(endpoint_id)
        if endpoint is None or not endpoint.router_bind:
            raise ConflictError(f"endpoint {endpoint_id} has no known router_bind")
        rpc_uri = resolve_rpc_uri(endpoint.router_bind, endpoint_id)

        command = Command(
            operation=wire.JOB_SUBMIT,
            content_type="application/json",
            envelope={
                "function_id": function_id,
                "function_name": None,
                "function_version": version,
                "params": params,
            },
        )
        result = send_command(rpc_uri, command, self._command_timeout_seconds)
        if result.is_err:
            raise UpstreamTimeoutError(str(result.unwrap_err()))

        command_result = result.unwrap()
        if not command_result.ok:
            raise ConflictError(command_result.error)
        return {"endpoint_id": endpoint_id, **(command_result.metadata or {})}

    def _resolve_endpoint_id(self, virtual_environment_id: str) -> str:
        virtual_environment = self._virtual_environment_repository.get(virtual_environment_id)
        leader_endpoint_id = virtual_environment.leader_endpoint_id if virtual_environment is not None else None
        if leader_endpoint_id is not None:
            leader = self._endpoint_repository.get(leader_endpoint_id)
            if leader is not None and leader.virtual_environment_id == virtual_environment_id:
                return leader_endpoint_id

        endpoints = self._endpoint_repository.list_by_virtual_environment(virtual_environment_id)
        if not endpoints:
            raise ConflictError("no endpoint assigned to this virtual environment")
        return endpoints[0].endpoint_id
