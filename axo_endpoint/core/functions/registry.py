from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional

from option import Err, Ok, Result

from axo_endpoint.core.errors import AxoError
from axo_endpoint.core.events.bus import Event, EventBus
from axo_shared.activity.models import FUNCTION_DELETED_EVENT, FUNCTION_UPDATED_EVENT
from axo_shared.functions.lifecycle import FunctionState, is_valid_transition
from axo_shared.functions.models import FunctionRecord
from axo_shared.functions.params_schema import ParamSpec
from axo_shared.runtime.spec import RuntimeSpec
from axo_endpoint.core.storage.backend import StorageBackend, StorageError, StorageKey


class RegistryError(AxoError):
    """Base class for FunctionRegistry-specific failures (not storage failures)."""

    code = 2000
    name = "REGISTRY_ERROR"


class FunctionRegistry:
    """Stores registered functions and changes their state over time."""

    def __init__(self, backend: StorageBackend[StorageKey, FunctionRecord], event_bus: EventBus) -> None:
        self._backend = backend
        self._event_bus = event_bus

    def register(
        self,
        function_id: str,
        name: str,
        code: bytes,
        now: float,
        runtime_spec: Optional[RuntimeSpec] = None,
        code_format: str = "cloudpickle",
        params_schema: Optional[List[ParamSpec]] = None,
    ) -> Result[StorageKey, StorageError]:
        """Saves a new function's code under function_id, auto-assigning the
        next version (max(existing versions for this function_id, default=0)
        + 1) -- version is never caller-supplied, guaranteeing the "versions
        increment" invariant rather than trusting callers to pass a strictly
        increasing value. function_id is the caller's derived
        (user_id, virtual_environment_id, name) identity; name is kept only
        as a separate display field."""
        list_result = self._backend.list_versions(function_id)
        if list_result.is_err:
            return Err(list_result.unwrap_err())
        existing_versions = [k.version or 0 for k in list_result.unwrap()]
        next_version = max(existing_versions, default=0) + 1

        key = StorageKey(id=function_id, version=next_version, alias=function_id)
        record = FunctionRecord(
            code=code,
            function_id=function_id,
            name=name,
            version=next_version,
            created_at=now,
            state=FunctionState.REGISTERED,
            runtime_spec=runtime_spec,
            code_format=code_format,
            params_schema=params_schema,
        )
        put_result = self._backend.put(key, record)
        if put_result.is_err:
            return Err(put_result.unwrap_err())

        self._event_bus.emit(
            Event(
                event_type=FunctionState.REGISTERED.value,
                payload={"function_id": key.id, "version": key.version},
                timestamp=now,
            )
        )
        return Ok(key)

    def get(self, key: StorageKey) -> Result[Optional[FunctionRecord], StorageError]:
        """Looks up a registered function by its key."""
        return self._backend.get(key)

    def transition(self, key: StorageKey, to: FunctionState, now: float) -> Result[FunctionRecord, RegistryError]:
        """Moves a function to a new state, if that change is allowed."""
        get_result = self._backend.get(key)
        if get_result.is_err:
            return Err(RegistryError(str(get_result.unwrap_err())))

        current = get_result.unwrap()
        if current is None:
            return Err(RegistryError(f"no FunctionRecord found for key {key}"))
        if not is_valid_transition(current.state, to):
            return Err(RegistryError(f"invalid transition {current.state} -> {to}"))

        updated = dataclasses.replace(current, state=to)
        put_result = self._backend.put(key, updated)
        if put_result.is_err:
            return Err(RegistryError(str(put_result.unwrap_err())))

        self._event_bus.emit(
            Event(
                event_type=to.value,
                payload={"function_id": key.id, "version": key.version},
                timestamp=now,
            )
        )
        return Ok(updated)

    def update(
        self,
        key: StorageKey,
        now: float,
        params_schema: Optional[List[ParamSpec]] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Result[FunctionRecord, RegistryError]:
        """In-place mutation of an existing version's params_schema/env_vars
        -- orthogonal to state (not a FunctionState transition), distinct
        from register() (no new version created). params_schema entries are
        merged additively: new names are appended, already-declared ones are
        left untouched. env_vars are merged into the existing RuntimeSpec's
        dict. Takes effect lazily -- a currently warm worker/container keeps
        running with its old config until it next naturally redeploys; this
        never forces a recycle."""
        get_result = self._backend.get(key)
        if get_result.is_err:
            return Err(RegistryError(str(get_result.unwrap_err())))
        current = get_result.unwrap()
        if current is None:
            return Err(RegistryError(f"no FunctionRecord found for key {key}"))

        merged_params_schema = current.params_schema
        if params_schema:
            existing_names = {p.name for p in (current.params_schema or [])}
            additions = [p for p in params_schema if p.name not in existing_names]
            merged_params_schema = (current.params_schema or []) + additions

        merged_runtime_spec = current.runtime_spec
        if env_vars:
            base_spec = current.runtime_spec or RuntimeSpec()
            merged_runtime_spec = dataclasses.replace(base_spec, env_vars={**base_spec.env_vars, **env_vars})

        updated = dataclasses.replace(
            current, params_schema=merged_params_schema, runtime_spec=merged_runtime_spec,
        )
        put_result = self._backend.put(key, updated)
        if put_result.is_err:
            return Err(RegistryError(str(put_result.unwrap_err())))

        self._event_bus.emit(
            Event(
                event_type=FUNCTION_UPDATED_EVENT,
                payload={"function_id": key.id, "version": key.version},
                timestamp=now,
            )
        )
        return Ok(updated)

    def delete(self, key: StorageKey, now: float) -> Result[StorageKey, RegistryError]:
        """Removes a registered function's code and metadata entirely.

        Never emits on failure -- mirrors register()'s behavior; the caller
        (FunctionDeleteHandler) surfaces the error via CommandResult.from_error,
        and ExternalEventForwardingBridge's error branch is what emits
        FunctionDeleteFailed externally.
        """
        get_result = self._backend.get(key)
        if get_result.is_err:
            return Err(RegistryError(str(get_result.unwrap_err())))
        if get_result.unwrap() is None:
            return Err(RegistryError(f"no FunctionRecord found for key {key}"))

        delete_result = self._backend.delete(key)
        if delete_result.is_err:
            return Err(RegistryError(str(delete_result.unwrap_err())))

        self._event_bus.emit(
            Event(
                event_type=FUNCTION_DELETED_EVENT,
                payload={"function_id": key.id, "version": key.version},
                timestamp=now,
            )
        )
        return Ok(key)
