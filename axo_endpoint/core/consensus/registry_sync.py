from __future__ import annotations

import base64
import json
import time
from typing import Callable, Dict, Optional

from axo_endpoint.core.consensus.dirty_tracker import DirtyTracker
from axo_endpoint.core.events.bus import Event, EventBus
from axo_shared.activity.models import FUNCTION_REPLICATED_EVENT
from axo_shared.functions.lifecycle import FunctionState
from axo_shared.functions.models import FunctionRecord
from axo_shared.functions.params_schema import parse_params_schema, params_schema_to_list
from axo_endpoint.core.functions.registry import FunctionRegistry
from axo_shared.runtime.spec import RuntimeSpec
from axo_endpoint.core.storage.backend import StorageBackend, StorageKey


def serialize_function_record(record: FunctionRecord) -> bytes:
    """Serializes a FunctionRecord to a JSON blob (code is base64-encoded inline)."""
    d = {
        "code_b64": base64.b64encode(record.code).decode("ascii"),
        "function_id": record.function_id,
        "name": record.name,
        "version": record.version,
        "created_at": record.created_at,
        "state": record.state.value,
        "runtime_spec": record.runtime_spec.to_dict() if record.runtime_spec else None,
        "code_format": record.code_format,
        "params_schema": params_schema_to_list(record.params_schema),
    }
    return json.dumps(d).encode("utf-8")


def deserialize_function_record(blob: bytes) -> FunctionRecord:
    """Deserializes a FunctionRecord from the JSON blob produced by serialize_function_record."""
    d = json.loads(blob.decode("utf-8"))
    return FunctionRecord(
        code=base64.b64decode(d["code_b64"]),
        function_id=d["function_id"],
        name=d["name"],
        version=d["version"],
        created_at=d["created_at"],
        state=FunctionState(d["state"]),
        runtime_spec=RuntimeSpec.from_dict(d["runtime_spec"]) if d.get("runtime_spec") else None,
        code_format=d.get("code_format", "cloudpickle"),
        params_schema=parse_params_schema(d.get("params_schema")) or None,
    )


def serialize_function_tombstone() -> bytes:
    """Marks a function_changes entry as "this key was deleted", rather than
    upserted -- travels through the exact same Dict[str, bytes] diff/replication
    path as a real record (encode_function_changes/decode_function_changes and
    friends already treat every value as an opaque JSON blob), so no change is
    needed anywhere else in the state_machine/state-sync wire encoding."""
    return json.dumps({"__tombstone__": True}).encode("utf-8")


def is_function_tombstone(blob: bytes) -> bool:
    """Distinguishes a deletion marker from a real serialized FunctionRecord blob."""
    try:
        return json.loads(blob.decode("utf-8")).get("__tombstone__", False) is True
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


class RegistrySyncBridge:
    """Bridges core.functions <-> core.consensus without either package
    depending on the other.

    Subscribes to the FunctionRegistry's existing lifecycle events and mirrors
    every change into the DirtyTracker (as leader), and applies incoming
    replicated records into the local backend (as follower).
    """

    def __init__(
        self,
        registry: FunctionRegistry,
        backend: StorageBackend[StorageKey, FunctionRecord],
        dirty_tracker: DirtyTracker,
        now_fn: Callable[[], float] = time.time,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._registry = registry
        self._backend = backend
        self._dirty_tracker = dirty_tracker
        self._now_fn = now_fn
        self._event_bus = event_bus

    def on_function_event(self, event: Event) -> None:
        """Subscribed to FunctionState.REGISTERED.value on the event bus."""
        function_id = event.payload["function_id"]
        version = event.payload["version"]
        key = StorageKey(id=function_id, version=version, alias=function_id)
        result = self._registry.get(key)
        if result.is_err:
            return
        record = result.unwrap()
        if record is None:
            return
        serialized = serialize_function_record(record)
        self._dirty_tracker.mark_function_dirty(
            f"{function_id}:{version}", serialized, self._now_fn()
        )

    def on_function_updated(self, event: Event) -> None:
        """Subscribed to FUNCTION_UPDATED_EVENT (FunctionRegistry.update()) --
        identical replication shape to on_function_event: fetch the current
        record by key, serialize, mark dirty. A second write under the same
        key is just a normal overwrite in both the local dict and the
        replicated Dict[str, bytes], so no new plumbing is needed beyond
        this subscription."""
        self.on_function_event(event)

    def on_function_deleted(self, event: Event) -> None:
        """Subscribed to FUNCTION_DELETED_EVENT (FunctionRegistry.delete()) --
        marks the same combined key dirty with a tombstone blob instead of a
        real serialized record, so the deletion replicates via the exact same
        dirty-tracker/STATE_SYNC_PUSH path as a registration."""
        function_id = event.payload["function_id"]
        version = event.payload["version"]
        self._dirty_tracker.mark_function_dirty(
            f"{function_id}:{version}", serialize_function_tombstone(), self._now_fn()
        )

    def apply_incoming(self, function_changes: Dict[str, bytes]) -> None:
        """Follower-side: writes replicated records straight into the backend,
        bypassing FunctionRegistry.register()/.delete() so this doesn't
        re-trigger dirty-tracking of already-replicated data. For every
        record actually absorbed (not a tombstone), emits
        FUNCTION_REPLICATED_EVENT so ExternalEventForwardingBridge can tell
        axo_vem this node has it too -- the live-registration path emits its
        own event via FunctionRegistry.register() instead, so this is the
        only source of that signal for a follower."""
        for combined_key, blob in function_changes.items():
            function_id, _, version_str = combined_key.rpartition(":")
            version = int(version_str)
            key = StorageKey(id=function_id, version=version, alias=function_id)
            if is_function_tombstone(blob):
                self._backend.delete(key)
                continue
            record = deserialize_function_record(blob)
            self._backend.put(key, record)
            if self._event_bus is not None:
                self._event_bus.emit(
                    Event(
                        event_type=FUNCTION_REPLICATED_EVENT,
                        payload={"function_id": function_id, "version": version},
                        timestamp=self._now_fn(),
                    )
                )
