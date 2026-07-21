from __future__ import annotations

from typing import List, Optional

from option import Err, Ok, Result

from axo_endpoint.core.data.bucket_models import BUCKET_REGISTERED_EVENT, DataBucket
from axo_endpoint.core.errors import BucketAlreadyExistsError
from axo_endpoint.core.events.bus import Event, EventBus
from axo_endpoint.core.storage.backend import StorageBackend, StorageError, StorageKey


class BucketRegistry:
    """Stores named, quota-enforced bucket metadata -- mirrors DataRegistry's
    "declare metadata ahead of use" shape, but far smaller: buckets aren't
    versioned and carry no chunk bytes of their own, only a name and a
    declared quota_bytes that DataRegisterHandler checks namespaced
    DATA_REGISTER calls against."""

    def __init__(self, catalog: StorageBackend[StorageKey, DataBucket], event_bus: EventBus) -> None:
        self._catalog = catalog
        self._event_bus = event_bus

    def register(self, name: str, quota_bytes: int, now: float) -> Result[DataBucket, StorageError]:
        key = StorageKey(id=name)
        existing = self._catalog.get(key)
        if existing.is_ok and existing.unwrap() is not None:
            return Err(BucketAlreadyExistsError(f"bucket '{name}' already exists", context={"name": name}))

        bucket = DataBucket(name=name, quota_bytes=quota_bytes, created_at=now)
        put_result = self._catalog.put(key, bucket)
        if put_result.is_err:
            return Err(put_result.unwrap_err())

        self._event_bus.emit(Event(
            event_type=BUCKET_REGISTERED_EVENT,
            payload={"name": name, "quota_bytes": quota_bytes, "created_at": now},
            timestamp=now,
        ))
        return Ok(bucket)

    def get(self, name: str) -> Result[Optional[DataBucket], StorageError]:
        return self._catalog.get(StorageKey(id=name))

    def list_buckets(self) -> List[DataBucket]:
        """Every DataBucket this node's catalog currently knows about --
        mirrors DataRegistry.list_records(); relies on the catalog backend
        being an InMemoryStorageBackend, same caveat as that method."""
        return self._catalog.values()
