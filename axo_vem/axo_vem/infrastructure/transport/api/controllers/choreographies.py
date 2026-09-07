from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from xolo.client.models import UserDTO

from axo_vem.application.choreography.cancel_choreography_run import CancelChoreographyRunUseCase
from axo_vem.application.choreography.create_choreography import CreateChoreographyUseCase
from axo_vem.application.choreography.delete_choreography import DeleteChoreographyUseCase
from axo_vem.application.choreography.purge_choreography import PurgeChoreographyUseCase
from axo_vem.application.choreography.run_choreography import RunChoreographyUseCase
from axo_vem.application.choreography.update_choreography import UpdateChoreographyUseCase
from axo_vem.domain.choreography.repository import ChoreographyRepository
from axo_vem.domain.choreography.run_repository import ChoreographyRunRepository
from axo_vem.domain.errors import NotFoundError
from axo_vem.domain.events.models import ChoreographyGraph


class _ChoreographyCreateRequest(BaseModel):
    name: str
    graph: ChoreographyGraph


class _ChoreographyUpdateRequest(BaseModel):
    name: str
    graph: ChoreographyGraph


def build_router(
    repository: ChoreographyRepository,
    run_repository: ChoreographyRunRepository,
    create_use_case: CreateChoreographyUseCase,
    update_use_case: UpdateChoreographyUseCase,
    delete_use_case: DeleteChoreographyUseCase,
    purge_use_case: PurgeChoreographyUseCase,
    current_user_dependency: Callable[..., UserDTO],
    run_use_case: Optional[RunChoreographyUseCase] = None,
    cancel_run_use_case: Optional[CancelChoreographyRunUseCase] = None,
) -> APIRouter:
    router = APIRouter(tags=["choreography"])

    @router.post("/choreographies", status_code=201)
    def create_choreography(
        body: _ChoreographyCreateRequest,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        return create_use_case.execute(name=body.name, owner_user_id=current_user.key, graph=body.graph)

    @router.get("/choreographies")
    def list_choreographies(current_user: UserDTO = Depends(current_user_dependency)):
        return [c.to_dict() for c in repository.list(owner_user_id=current_user.key)]

    @router.get("/choreographies/{choreography_id}")
    def get_choreography(choreography_id: str, current_user: UserDTO = Depends(current_user_dependency)):
        choreography = repository.get(choreography_id)
        if choreography is None:
            raise HTTPException(status_code=404, detail="choreography not found")
        choreography.assert_owner(current_user.key)
        body = choreography.to_dict()
        body["has_active_run"] = run_repository.has_active_run(choreography_id)
        return body

    @router.put("/choreographies/{choreography_id}")
    def update_choreography(
        choreography_id: str,
        body: _ChoreographyUpdateRequest,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        return update_use_case.execute(
            choreography_id=choreography_id, current_user_id=current_user.key, name=body.name, graph=body.graph,
        )

    @router.delete("/choreographies/{choreography_id}", status_code=204)
    def delete_choreography(choreography_id: str, current_user: UserDTO = Depends(current_user_dependency)):
        delete_use_case.execute(choreography_id=choreography_id, current_user_id=current_user.key)
        return None

    @router.delete("/choreographies/{choreography_id}/purge")
    def purge_choreography(choreography_id: str, current_user: UserDTO = Depends(current_user_dependency)):
        purge_use_case.execute(choreography_id=choreography_id, current_user_id=current_user.key)
        return {"choreography_id": choreography_id}

    if run_use_case is not None:
        @router.post("/choreographies/{choreography_id}/validate")
        def validate_choreography(choreography_id: str, current_user: UserDTO = Depends(current_user_dependency)):
            choreography = repository.get(choreography_id)
            if choreography is None:
                raise HTTPException(status_code=404, detail="choreography not found")
            choreography.assert_owner(current_user.key)
            violations = run_use_case.validate(choreography)
            return {
                "ok": not violations,
                "violations": [
                    {
                        "node_id": v.node_id, "function_id": v.function_id,
                        "required_concurrency": v.required_concurrency, "max_concurrency": v.max_concurrency,
                    }
                    for v in violations
                ],
            }

        @router.post("/choreographies/{choreography_id}/run")
        def run_choreography(choreography_id: str, current_user: UserDTO = Depends(current_user_dependency)):
            return run_use_case.execute(choreography_id=choreography_id, current_user_id=current_user.key)

        @router.get("/choreographies/{choreography_id}/runs")
        def list_runs(choreography_id: str, current_user: UserDTO = Depends(current_user_dependency)):
            choreography = repository.get(choreography_id)
            if choreography is None:
                raise HTTPException(status_code=404, detail="choreography not found")
            choreography.assert_owner(current_user.key)
            return [r.to_dict() for r in run_repository.list_by_choreography(choreography_id)]

        @router.get("/choreographies/{choreography_id}/runs/{run_id}")
        def get_run(choreography_id: str, run_id: str, current_user: UserDTO = Depends(current_user_dependency)):
            choreography = repository.get(choreography_id)
            if choreography is None:
                raise HTTPException(status_code=404, detail="choreography not found")
            choreography.assert_owner(current_user.key)
            run = run_repository.get(run_id)
            if run is None or run.choreography_id != choreography_id:
                raise HTTPException(status_code=404, detail="run not found")
            return run.to_dict()

    if cancel_run_use_case is not None:
        @router.post("/choreographies/{choreography_id}/runs/{run_id}/cancel")
        def cancel_run(choreography_id: str, run_id: str, current_user: UserDTO = Depends(current_user_dependency)):
            try:
                return cancel_run_use_case.execute(run_id=run_id, current_user_id=current_user.key)
            except NotFoundError:
                raise HTTPException(status_code=404, detail="run not found")

    return router
