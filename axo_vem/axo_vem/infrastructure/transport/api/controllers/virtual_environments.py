from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from xolo.client.models import UserDTO

from axo_vem.application.workspace.create_virtual_environment import CreateVirtualEnvironmentUseCase
from axo_vem.application.workspace.delete_virtual_environment import DeleteVirtualEnvironmentUseCase
from axo_vem.application.workspace.purge_virtual_environment import PurgeVirtualEnvironmentUseCase
from axo_vem.application.workspace.update_virtual_environment import UpdateVirtualEnvironmentUseCase
from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository


class _VirtualEnvironmentCreateRequest(BaseModel):
    name: str
    cpu: float
    ram: int
    disk: int


class _VirtualEnvironmentUpdateRequest(BaseModel):
    name: str
    cpu: float
    ram: int
    disk: int


def build_router(
    repository: VirtualEnvironmentRepository,
    create_use_case: CreateVirtualEnvironmentUseCase,
    update_use_case: UpdateVirtualEnvironmentUseCase,
    delete_use_case: DeleteVirtualEnvironmentUseCase,
    purge_use_case: PurgeVirtualEnvironmentUseCase,
    current_user_dependency: Callable[..., UserDTO],
) -> APIRouter:
    router = APIRouter(tags=["virtual environment"])

    @router.post("/virtual-environments", status_code=201)
    def create_virtual_environment(
        body: _VirtualEnvironmentCreateRequest,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        return create_use_case.execute(
            name=body.name, owner_user_id=current_user.key, cpu=body.cpu, ram=body.ram, disk=body.disk,
        )

    @router.get("/virtual-environments")
    def list_virtual_environments(
        name: Optional[str] = None,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        if name is not None:
            virtual_environments = repository.search_by_name(name, owner_user_id=current_user.key)
        else:
            virtual_environments = repository.list(owner_user_id=current_user.key)
        return [ve.to_dict() for ve in virtual_environments]

    @router.get("/virtual-environments/{virtual_environment_id}")
    def get_virtual_environment(
        virtual_environment_id: str,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        virtual_environment = repository.get(virtual_environment_id)
        if virtual_environment is None:
            raise HTTPException(status_code=404, detail="virtual environment not found")
        virtual_environment.assert_owner(current_user.key)
        return virtual_environment.to_dict()

    @router.put("/virtual-environments/{virtual_environment_id}")
    def update_virtual_environment(
        virtual_environment_id: str,
        body: _VirtualEnvironmentUpdateRequest,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        return update_use_case.execute(
            virtual_environment_id=virtual_environment_id,
            current_user_id=current_user.key,
            name=body.name,
            cpu=body.cpu,
            ram=body.ram,
            disk=body.disk,
        )

    @router.delete("/virtual-environments/{virtual_environment_id}", status_code=204)
    def delete_virtual_environment(
        virtual_environment_id: str,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        delete_use_case.execute(virtual_environment_id=virtual_environment_id, current_user_id=current_user.key)
        return None

    @router.delete("/virtual-environments/{virtual_environment_id}/purge")
    def purge_virtual_environment(
        virtual_environment_id: str,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        purge_use_case.execute(virtual_environment_id=virtual_environment_id, current_user_id=current_user.key)
        return {"virtual_environment_id": virtual_environment_id}

    return router
