from __future__ import annotations

from typing import Any, Dict, List, Optional

from axo_shared import wire
from axo_shared.protocol import Command

from axo_vem.domain.compute.repository import EndpointRepository, FunctionRepository
from axo_vem.domain.errors import ConflictError, NotFoundError, UpstreamTimeoutError
from axo_vem.infrastructure.transport.zmq_command.endpoint_client import resolve_rpc_uri, send_command


class UpdateFunctionUseCase:
    """Replaces the body of the former
    PATCH /endpoints/{endpoint_id}/functions/{name}/{version} route handler.
    An in-place params_schema/env_vars mutation, no new version, no code
    change -- takes effect lazily, an already-running worker/container
    keeps its old config until it next naturally redeploys. Same
    endpoint-resolution fix as DeleteFunctionUseCase: routes off the
    function's own recorded endpoint_id list, never a caller-picked
    endpoint or a re-derived function_id hash -- tries each recorded
    endpoint in order (FUNCTION_UPDATE is leader-gated cluster-wide, so any
    one live holder is enough), only failing once every candidate is
    exhausted."""

    def __init__(
        self,
        function_repository: FunctionRepository,
        endpoint_repository: EndpointRepository,
        command_timeout_seconds: float = 3.0,
    ) -> None:
        self._function_repository = function_repository
        self._endpoint_repository = endpoint_repository
        self._command_timeout_seconds = command_timeout_seconds

    def execute(
        self,
        *,
        function_id: str,
        version: int,
        current_user_id: str,
        params_schema: Optional[List[Dict[str, Any]]] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        function = self._function_repository.get(function_id, version)
        if function is None:
            raise NotFoundError("function version not found")
        if not function.endpoint_id:
            raise ConflictError("function has no recorded endpoint to route this request to")

        envelope: Dict[str, Any] = {"function_id": function_id, "version": version}
        if params_schema:
            envelope["params_schema"] = params_schema
        if env_vars:
            envelope["env_vars"] = env_vars
        command = Command(operation=wire.FUNCTION_UPDATE, content_type="application/json", envelope=envelope)

        last_error: Optional[str] = None
        for candidate_endpoint_id in function.endpoint_id:
            endpoint = self._endpoint_repository.get(candidate_endpoint_id)
            if endpoint is None or not endpoint.router_bind:
                last_error = f"endpoint {candidate_endpoint_id} is unreachable"
                continue
            rpc_uri = resolve_rpc_uri(endpoint.router_bind, endpoint.endpoint_id)
            result = send_command(rpc_uri, command, self._command_timeout_seconds)
            if result.is_err:
                last_error = str(result.unwrap_err())
                continue

            command_result = result.unwrap()
            if not command_result.ok:
                raise ConflictError(command_result.error)
            return {"function_id": function_id, "version": version}

        raise UpstreamTimeoutError(last_error or "no recorded endpoint was reachable")
