from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo.collection import Collection
from xolo.client.models import UserDTO

from axo_shared import wire
from axo_shared.protocol import Command

from axo_vem.application.compute.submit_function_job import SubmitFunctionJobUseCase
from axo_vem.domain.errors import NotFoundError
from axo_vem.domain.execution.repository import JobRepository
from axo_vem.infrastructure.transport.zmq_command.endpoint_client import resolve_rpc_uri, send_command


class _JobSubmitRequest(BaseModel):
    function_id: str
    function_name: Optional[str] = None
    function_version: int
    params: Dict[str, Any] = {}


class _FunctionJobSubmitRequest(BaseModel):
    params: Dict[str, Any] = {}


def build_router(
    job_repository: JobRepository,
    current_user_dependency: Callable[..., UserDTO],
    endpoints: Optional[Collection] = None,
    command_timeout_seconds: float = 3.0,
    submit_function_job_use_case: Optional[SubmitFunctionJobUseCase] = None,
) -> APIRouter:
    router = APIRouter(tags=["job telemetry"])

    if submit_function_job_use_case is not None:

        @router.post("/functions/{function_id}/{version}/jobs", tags=["function registries"])
        def submit_function_job(
            function_id: str,
            version: int,
            body: _FunctionJobSubmitRequest,
            _current_user: UserDTO = Depends(current_user_dependency),
        ):
            """Callers never pick an endpoint -- the target node is resolved
            server-side from the function's own virtual_environment_id (see
            SubmitFunctionJobUseCase). Returns the same shape
            POST /endpoints/{endpoint_id}/jobs does, plus which endpoint_id
            it actually landed on, so the caller can poll
            GET /endpoints/{endpoint_id}/jobs/{job_id} for the result."""
            return submit_function_job_use_case.execute(
                function_id=function_id, version=version, params=body.params,
            )

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str, _current_user: UserDTO = Depends(current_user_dependency)):
        job = job_repository.get(job_id)
        if job is None:
            raise NotFoundError("job not found")
        return job.to_dict()

    @router.get("/functions/{function_id}/jobs")
    def list_jobs_for_function(
        function_id: str,
        version: Optional[int] = None,
        _current_user: UserDTO = Depends(current_user_dependency),
    ):
        """Job history for one function (optionally scoped to one version),
        newest first -- backs the Jobs table on the function detail page.
        Sourced from the jobs read model, not a live node query."""
        return [job.to_dict() for job in job_repository.list_by_function(function_id, version)]

    if endpoints is not None:

        @router.post("/endpoints/{endpoint_id}/jobs", tags=["endpoint management"])
        def submit_job(
            endpoint_id: str,
            body: _JobSubmitRequest,
            _current_user: UserDTO = Depends(current_user_dependency),
        ):
            """Proxies JOB_SUBMIT straight to the target endpoint's ROUTER --
            same relay shape as register_function/create_bucket. Submission
            is fire-and-forget from this route's perspective (JOB_SUBMIT
            itself is queued/async on the node); poll
            GET /endpoints/{endpoint_id}/jobs/{job_id} for the result.

            function_id is the node's actual catalog lookup key (see
            JobSubmitHandler.handle()) -- unlike register_function/
            delete_function/update_function, which only ever get a caller-
            supplied name and must derive function_id themselves via
            compute_function_id, the caller here already knows function_id
            (it's what GET /functions/{function_id} was keyed on), so it's
            taken directly rather than re-derived. function_name, if given,
            travels along only for the node's own logging."""
            doc = endpoints.find_one({"_id": endpoint_id})
            if doc is None:
                raise HTTPException(status_code=404, detail="endpoint not found")
            router_bind = doc.get("router_bind")
            if not router_bind:
                raise HTTPException(status_code=409, detail="endpoint has no known router_bind")
            rpc_uri = resolve_rpc_uri(router_bind, endpoint_id)

            command = Command(
                operation=wire.JOB_SUBMIT,
                content_type="application/json",
                envelope={
                    "function_id": body.function_id,
                    "function_name": body.function_name,
                    "function_version": body.function_version,
                    "params": body.params,
                },
            )
            result = send_command(rpc_uri, command, command_timeout_seconds)
            if result.is_err:
                raise HTTPException(status_code=504, detail=str(result.unwrap_err()))
            command_result = result.unwrap()
            if not command_result.ok:
                raise HTTPException(status_code=409, detail=command_result.error)
            return {"endpoint_id": endpoint_id, **(command_result.metadata or {})}

        @router.get("/endpoints/{endpoint_id}/jobs/{job_id}", tags=["endpoint management"])
        def poll_job_result(
            endpoint_id: str,
            job_id: str,
            _current_user: UserDTO = Depends(current_user_dependency),
        ):
            """Relays JOB_RESULT directly to the node -- the low-latency
            polling path, ahead of the Kurrent-to-Mongo pipeline, and the
            only source of a job's actual result values/error today (the
            jobs read model deliberately doesn't persist them, only
            status/timing -- see domain/execution/job.py)."""
            doc = endpoints.find_one({"_id": endpoint_id})
            if doc is None:
                raise HTTPException(status_code=404, detail="endpoint not found")
            router_bind = doc.get("router_bind")
            if not router_bind:
                raise HTTPException(status_code=409, detail="endpoint has no known router_bind")
            rpc_uri = resolve_rpc_uri(router_bind, endpoint_id)

            command = Command(
                operation=wire.JOB_RESULT,
                content_type="application/json",
                envelope={"job_id": job_id},
            )
            result = send_command(rpc_uri, command, command_timeout_seconds)
            if result.is_err:
                raise HTTPException(status_code=504, detail=str(result.unwrap_err()))
            command_result = result.unwrap()
            if not command_result.ok:
                raise HTTPException(status_code=409, detail=command_result.error)
            return {"job_id": job_id, "endpoint_id": endpoint_id, **(command_result.metadata or {})}

    return router
