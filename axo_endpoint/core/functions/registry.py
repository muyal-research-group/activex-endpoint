from __future__ import annotations

import dataclasses
from typing import Optional

from option import Err, Ok, Result

from axo_endpoint.core.errors import AxoError
from axo_endpoint.core.events.bus import Event, EventBus
from axo_endpoint.core.functions.lifecycle import FunctionState, is_valid_transition
from axo_endpoint.core.functions.models import FunctionRecord
from axo_endpoint.core.storage.backend import StorageBackend, StorageError, StorageKey


class RegistryError(AxoError):
    """Base class for FunctionRegistry-specific failures (not storage failures)."""

    code = 2000
    name = "REGISTRY_ERROR"


class FunctionRegistry:
    """Stores registered functions and changes their state over time."""

    def __init__(self, backend: StorageBackend[FunctionRecord], event_bus: EventBus) -> None:
        self._backend = backend
        self._event_bus = event_bus

    def register(self, name: str, version: int, code: bytes, now: float) -> Result[StorageKey, StorageError]:
        """Saves a new function's code under a name and version."""
        key = StorageKey(id=name, version=version, alias=name)
        record = FunctionRecord(
            code=code, name=name, version=version, created_at=now, state=FunctionState.REGISTERED
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
