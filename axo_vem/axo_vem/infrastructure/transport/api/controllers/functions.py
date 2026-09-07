from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from pymongo.collection import Collection
from xolo.client.models import UserDTO

from axo_shared.functions.source import FunctionSourceError, validate_function_source

from axo_vem.application.compute.delete_function import DeleteFunctionUseCase
from axo_vem.application.compute.purge_function_version import PurgeFunctionVersionUseCase
from axo_vem.application.compute.register_function import RegisterFunctionUseCase
from axo_vem.application.compute.update_function import UpdateFunctionUseCase
from axo_vem.infrastructure.transport.api.serialization import strip_id


class _FunctionUpdateRequest(BaseModel):
    params_schema: Optional[List[Dict[str, Any]]] = None
    env_vars: Optional[Dict[str, str]] = None


def build_router(
    functions: Collection,
    current_user_dependency: Callable[..., UserDTO],
    register_use_case: RegisterFunctionUseCase,
    delete_use_case: DeleteFunctionUseCase,
    update_use_case: UpdateFunctionUseCase,
    purge_use_case: PurgeFunctionVersionUseCase,
) -> APIRouter:
    router = APIRouter(tags=["function registries"])

    @router.get("/functions")
    def list_functions(_current_user: UserDTO = Depends(current_user_dependency)):
        return [strip_id(doc) for doc in functions.find()]

    @router.get("/functions/{function_id}")
    def get_function_versions(function_id: str, _current_user: UserDTO = Depends(current_user_dependency)):
        """Every version of one function -- _id is f"{function_id}:{version}",
        so a prefix match on the function_id field (not _id) finds them all."""
        docs = list(functions.find({"function_id": function_id}))
        if not docs:
            raise HTTPException(status_code=404, detail="function not found")
        return [strip_id(d) for d in docs]

    @router.post("/functions", status_code=201)
    async def register_function(
        virtual_environment_id: str = Form(...),
        name: str = Form(...),
        runtime_spec: Optional[str] = Form(None),
        params_schema: Optional[str] = Form(None),
        code: UploadFile = File(...),
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        """Registers a function into a virtual environment the caller owns --
        no endpoint_id from the caller; RegisterFunctionUseCase auto-picks
        the target endpoint currently assigned to that VE.

        `code` is raw .py source -- must define a top-level function named
        exactly `name` (e.g. name="add" requires `def add(params, ctx):
        ...`). This service only statically validates that shape via
        axo_shared.functions.source.validate_function_source (parses the
        AST, never executes it) and forwards the raw source onward
        untouched -- actual execution is deferred to the target node's own
        cold start (forked worker or spawned container), never here. This
        pure-transport validation (JSON decode + AST parse) stays in the
        controller rather than the use case, matching how pydantic bodies
        elsewhere in this API handle 422s.
        """
        parsed_runtime_spec = None
        if runtime_spec:
            try:
                parsed_runtime_spec = json.loads(runtime_spec)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=422, detail=f"runtime_spec is not valid JSON: {exc}")

        parsed_params_schema = None
        if params_schema:
            try:
                parsed_params_schema = json.loads(params_schema)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=422, detail=f"params_schema is not valid JSON: {exc}")

        source = await code.read()
        try:
            validate_function_source(source, name)
        except FunctionSourceError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        return register_use_case.execute(
            virtual_environment_id=virtual_environment_id,
            current_user_id=current_user.key,
            name=name,
            code=source,
            runtime_spec=parsed_runtime_spec,
            params_schema=parsed_params_schema,
        )

    @router.delete("/functions/{function_id}/{version}")
    def delete_function(
        function_id: str,
        version: int,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        """Routes FUNCTION_DELETE to the function version's own recorded
        endpoint -- no endpoint_id from the caller."""
        return delete_use_case.execute(function_id=function_id, version=version, current_user_id=current_user.key)

    @router.patch("/functions/{function_id}/{version}")
    def update_function(
        function_id: str,
        version: int,
        body: _FunctionUpdateRequest,
        current_user: UserDTO = Depends(current_user_dependency),
    ):
        """In-place params_schema/env_vars mutation, no new version, no code
        change -- same endpoint resolution as delete_function above."""
        return update_use_case.execute(
            function_id=function_id,
            version=version,
            current_user_id=current_user.key,
            params_schema=body.params_schema,
            env_vars=body.env_vars,
        )

    @router.delete("/functions/{function_id}/{version}/purge")
    def purge_function_version(
        function_id: str,
        version: int,
        _current_user: UserDTO = Depends(current_user_dependency),
    ):
        """Hard-deletes this function version's read-model doc and its
        unified_activity history, and permanently deletes its isolated
        Kurrent stream. Distinct from delete_function above (which only
        soft-deletes via FUNCTION_DELETE/FunctionDeleted). Requires the
        version to already be soft-deleted."""
        return purge_use_case.execute(function_id=function_id, version=version)

    return router
