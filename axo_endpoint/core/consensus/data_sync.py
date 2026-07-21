from __future__ import annotations

import dataclasses
import json
import time
from typing import Callable, Dict

from axo_endpoint.core.consensus.dirty_tracker import DirtyTracker
from axo_endpoint.core.data.models import DataRecord
from axo_endpoint.core.data.registry import DataRegistry
from axo_endpoint.core.events.bus import Event
from axo_endpoint.core.storage.backend import StorageBackend, StorageKey


def serialize_data_record(record: DataRecord) -> bytes:
    """Serializes a DataRecord to a JSON blob.

    No base64 layer needed, unlike serialize_function_record -- DataRecord
    holds no raw bytes inline, only scalars.
    """
    return json.dumps(dataclasses.asdict(record)).encode("utf-8")


def deserialize_data_record(blob: bytes) -> DataRecord:
    """Deserializes a DataRecord from the JSON blob produced by serialize_data_record."""
    return DataRecord(**json.loads(blob.decode("utf-8")))


def serialize_data_tombstone() -> bytes:
    """Marks a data_changes entry as "this key was deleted", rather than
    upserted -- travels through the exact same Dict[str, bytes] diff/
    replication path as a real record (encode_data_changes/decode_data_changes
    and friends already treat every value as an opaque JSON blob), so no
    change is needed anywhere else in the state_machine/state-sync wire
    encoding. Mirrors registry_sync.serialize_function_tombstone()."""
    return json.dumps({"__tombstone__": True}).encode("utf-8")


def is_data_tombstone(blob: bytes) -> bool:
    """Distinguishes a deletion marker from a real serialized DataRecord blob."""
    try:
        return json.loads(blob.decode("utf-8")).get("__tombstone__", False) is True
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


class DataRegistrySyncBridge:
    """Bridges core.data <-> core.consensus without either package depending
    on the other, mirroring RegistrySyncBridge for the data domain.

    Subscribes to DataRegistry's DATA_REGISTERED_EVENT/DATA_DELETED_EVENT and
    mirrors every change into the (shared) DirtyTracker (as leader), and
    applies incoming replicated catalog records into the local backend (as
    follower).

    Note: this only replicates the DataRecord *catalog* entry, not the
    underlying bytes -- those arrive separately via the blob-stream path on
    its own throttled schedule. A job routed to a follower whose blob-stream
    hasn't caught up yet will see a catalog hit but an IONotFoundError on the
    actual read; that's an accepted consequence of the two-channel design,
    not something this bridge tries to close.
    """

    def __init__(
        self,
        registry: DataRegistry,
        catalog: StorageBackend[StorageKey, DataRecord],
        dirty_tracker: DirtyTracker,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._registry = registry
        self._catalog = catalog
        self._dirty_tracker = dirty_tracker
        self._now_fn = now_fn

    def on_data_event(self, event: Event) -> None:
        """Subscribed to DATA_REGISTERED_EVENT on the event bus."""
        data_id = event.payload["data_id"]
        version = event.payload["version"]
        key = StorageKey(id=data_id, version=version, alias=data_id)
        result = self._registry.get(key)
        if result.is_err:
            return
        record = result.unwrap()
        if record is None:
            return
        serialized = serialize_data_record(record)
        self._dirty_tracker.mark_data_dirty(f"{data_id}:{version}", serialized, self._now_fn())

    def on_data_deleted(self, event: Event) -> None:
        """Subscribed to DATA_DELETED_EVENT (DataRegistry.delete()) -- marks
        the same combined key dirty with a tombstone blob instead of a real
        serialized record, so the deletion replicates via the exact same
        dirty-tracker/STATE_SYNC_PUSH path as a registration. Mirrors
        RegistrySyncBridge.on_function_deleted()."""
        data_id = event.payload["data_id"]
        version = event.payload["version"]
        self._dirty_tracker.mark_data_dirty(
            f"{data_id}:{version}", serialize_data_tombstone(), self._now_fn()
        )

    def apply_incoming(self, data_changes: Dict[str, bytes]) -> None:
        """Follower-side: writes replicated catalog records straight into the
        backend, bypassing DataRegistry.register() so this doesn't re-trigger
        dirty-tracking of already-replicated data.

        A tombstone entry goes through DataRegistry.delete() instead of a
        raw catalog removal, unlike RegistrySyncBridge's equivalent (which
        bypasses FunctionRegistry.delete() entirely) -- data deletion also
        has to remove this node's local chunk bytes, logic DataRegistry.delete()
        already implements and this bridge would otherwise have to duplicate.
        The one accepted side effect: DataRegistry.delete() re-emits
        DATA_DELETED_EVENT locally, re-dirtying this same key in our own
        DirtyTracker -- harmless, since a follower's DirtyTracker is never
        drained/flushed (only the leader's consensus tick does that) -- and
        forwards a second DataDeleted to axo_vem, which is also
        harmless (idempotent removal), mirroring the same "every node
        reports its own local truth" redundancy already accepted for
        DataUploadCompleted. A tombstone for a key this node never had
        locally (never finished replicating, or already deleted) is not an
        error -- the goal state (gone) is already achieved either way."""
        for combined_key, blob in data_changes.items():
            name, _, version_str = combined_key.rpartition(":")
            if is_data_tombstone(blob):
                self._registry.delete(name, int(version_str), self._now_fn())
                continue
            record = deserialize_data_record(blob)
            key = StorageKey(id=name, version=int(version_str), alias=name)
            self._catalog.put(key, record)
