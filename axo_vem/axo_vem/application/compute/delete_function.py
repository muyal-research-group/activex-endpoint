from __future__ import annotations

from typing import Any, Dict, Optional

from axo_shared import wire
from axo_shared.protocol import Command

from axo_vem.domain.compute.repository import EndpointRepository, FunctionRepository
from axo_vem.domain.errors import ConflictError, NotFoundError, UpstreamTimeoutError
from axo_vem.domain.execution.job import JobStatus
from axo_vem.domain.execution.repository import JobRepository
from axo_vem.infrastructure.transport.zmq_command.endpoint_client import resolve_rpc_uri, send_command


class DeleteFunctionUseCase:
    """Replaces the body of the former
    DELETE /endpoints/{endpoint_id}/functions/{name}/{version} route handler.

    Routing used to be re-derived by recomputing function_id from
    (caller's user id, whichever endpoint the caller picked, name) -- if
    that endpoint's virtual_environment_id differed from the one used at
    register time (or the caller picked an unrelated endpoint entirely),
    the hash came out different and the lookup permanently failed with
    "no FunctionRecord found for key StorageKey(...)". This use case
    instead resolves the target endpoint from the function version's own
    recorded endpoint_id list (every node currently known to hold a
    replica -- see domain/compute/function.py's docstring), so routing no
    longer depends on any caller input at all beyond function_id/version.
    FUNCTION_DELETE is leader-gated cluster-wide, so any one live holder is
    enough to reach it -- this tries each recorded endpoint in order,
    skipping ones with no known router_bind and falling through to the next
    on an upstream timeout, only failing once every candidate is
    exhausted."""

    def __init__(
        self,
        function_repository: FunctionRepository,
        endpoint_repository: EndpointRepository,
        job_repository: JobRepository,
        command_timeout_seconds: float = 3.0,
    ) -> None:
        self._function_repository = function_repository
        self._endpoint_repository = endpoint_repository
        self._job_repository = job_repository
        self._command_timeout_seconds = command_timeout_seconds

    def execute(self, *, function_id: str, version: int, current_user_id: str) -> Dict[str, Any]:
        # current_user_id is accepted but not yet enforced as an ownership
        # check -- owner_user_id is never populated on function docs by any
        # current axo_endpoint producer, so there's nothing to check against
        # today. Keeping the parameter makes the signature self-documenting
        # about what a future caller-identity-aware check would need.
        function = self._function_repository.get(function_id, version)
        if function is None:
            raise NotFoundError("function version not found")
        if function.container_status == "running":
            raise ConflictError("function has a live deployed container -- stop it before deleting")
        active_jobs = self._job_repository.list_by_function(function_id, version)
        if any(job.status in (JobStatus.QUEUED, JobStatus.STARTED) for job in active_jobs):
            raise ConflictError("function has jobs still queued or running -- wait for them to finish before deleting")
        if not function.endpoint_id:
            raise ConflictError("function has no recorded endpoint to route this request to")

        command = Command(
            operation=wire.FUNCTION_DELETE,
            content_type="application/json",
            envelope={"function_id": function_id, "version": version},
        )

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
