from __future__ import annotations

import dataclasses
import json
import time
from typing import Callable, Dict

from axo_endpoint.core.consensus.dirty_tracker import DirtyTracker
from axo_endpoint.core.data.bucket_models import DataBucket
from axo_endpoint.core.data.bucket_registry import BucketRegistry
from axo_endpoint.core.events.bus import Event
from axo_endpoint.core.storage.backend import StorageBackend, StorageKey


def serialize_data_bucket(bucket: DataBucket) -> bytes:
    """Serializes a DataBucket to a JSON blob -- no base64 layer needed,
    mirrors serialize_data_record (scalars only, no raw bytes inline)."""
    return json.dumps(dataclasses.asdict(bucket)).encode("utf-8")


def deserialize_data_bucket(blob: bytes) -> DataBucket:
    """Deserializes a DataBucket from the JSON blob produced by serialize_data_bucket."""
    return DataBucket(**json.loads(blob.decode("utf-8")))


class BucketRegistrySyncBridge:
    """Bridges core.data.bucket_registry <-> core.consensus without either
    package depending on the other, mirroring DataRegistrySyncBridge for the
    bucket domain.

    Subscribes to BucketRegistry's BUCKET_REGISTERED_EVENT and mirrors every
    change into the (shared) DirtyTracker (as leader), and applies incoming
    replicated catalog entries into the local backend (as follower). Keyed by
    bucket name alone (no version -- buckets aren't versioned, unlike
    functions/data's "name:version" combined key).
    """

    def __init__(
        self,
        registry: BucketRegistry,
        catalog: StorageBackend[StorageKey, DataBucket],
        dirty_tracker: DirtyTracker,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._registry = registry
        self._catalog = catalog
        self._dirty_tracker = dirty_tracker
        self._now_fn = now_fn

    def on_bucket_event(self, event: Event) -> None:
        """Subscribed to BUCKET_REGISTERED_EVENT on the event bus."""
        name = event.payload["name"]
        result = self._registry.get(name)
        if result.is_err:
            return
        bucket = result.unwrap()
        if bucket is None:
            return
        serialized = serialize_data_bucket(bucket)
        self._dirty_tracker.mark_bucket_dirty(name, serialized, self._now_fn())

    def apply_incoming(self, bucket_changes: Dict[str, bytes]) -> None:
        """Follower-side: writes replicated catalog entries straight into the
        backend, bypassing BucketRegistry.register() so this doesn't
        re-trigger dirty-tracking of already-replicated data."""
        for name, blob in bucket_changes.items():
            bucket = deserialize_data_bucket(blob)
            self._catalog.put(StorageKey(id=name), bucket)
