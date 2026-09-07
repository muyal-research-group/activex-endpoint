from __future__ import annotations

from typing import Dict, Generic, List, Optional, Tuple, TypeVar

from option import Ok, Result

from axo_endpoint.core.storage.backend import StorageBackend, StorageError, StorageKey

V = TypeVar("V")


class InMemoryStorageBackend(StorageBackend[StorageKey, V], Generic[V]):
    """Process-local, dict-backed StorageBackend. Not persisted across restarts."""

    def __init__(self) -> None:
        self._storage: Dict[StorageKey, V] = {}
        self._by_id_version: Dict[Tuple[str, int], StorageKey] = {}
        self._by_alias_version: Dict[Tuple[str, int], StorageKey] = {}

    def put(self, key: StorageKey, value: V) -> Result[str, StorageError]:
        """Saves a value under a key."""
        self._storage[key] = value
        if key.version is not None:
            self._by_id_version[(key.id, key.version)] = key
            if key.alias is not None:
                self._by_alias_version[(key.alias, key.version)] = key
        return Ok(key.id)

    def get(self, key: StorageKey) -> Result[Optional[V], StorageError]:
        """Looks up a value using whichever parts of the key (id, version, alias) were given."""
        if key.alias is not None and key.version is not None:
            return self.get_by_alias_version(key.alias, key.version)
        if key.version is not None:
            return self.get_by_id_version(key.id, key.version)
        if key.alias is not None:
            return self.get_by_alias(key.alias)
        return self.get_by_id(key.id)

    def exists(self, key: StorageKey) -> Result[bool, StorageError]:
        """Checks whether a value exists for a key."""
        return Ok(self.get(key).unwrap() is not None)

    def delete(self, key: StorageKey) -> Result[None, StorageError]:
        """Removes a value and cleans up both reverse-lookup indexes."""
        self._storage.pop(key, None)
        if key.version is not None:
            self._by_id_version.pop((key.id, key.version), None)
            if key.alias is not None:
                self._by_alias_version.pop((key.alias, key.version), None)
        return Ok(None)

    def list_versions(self, id: str) -> Result[List[StorageKey], StorageError]:
        """Every key currently stored under this id, across all versions --
        used by FunctionRegistry.register() to compute
        next_version = max(existing versions, default=0) + 1."""
        return Ok([k for k in self._storage if k.id == id])

    def get_by_id(self, id: str) -> Result[Optional[V], StorageError]:
        """Looks up the newest version stored under an id."""
        keys = [k for k in self._storage if k.id == id]
        if not keys:
            return Ok(None)
        latest = max(keys, key=lambda k: k.version or 0)
        return Ok(self._storage[latest])

    def get_by_id_version(self, id: str, version: int) -> Result[Optional[V], StorageError]:
        """Looks up a specific version stored under an id."""
        key = self._by_id_version.get((id, version))
        return Ok(self._storage[key] if key is not None else None)

    def get_by_alias(self, alias: str) -> Result[Optional[V], StorageError]:
        """Looks up the newest version stored under an alias."""
        keys = [k for k in self._storage if k.alias == alias]
        if not keys:
            return Ok(None)
        latest = max(keys, key=lambda k: k.version or 0)
        return Ok(self._storage[latest])

    def get_by_alias_version(self, alias: str, version: int) -> Result[Optional[V], StorageError]:
        """Looks up a specific version stored under an alias."""
        key = self._by_alias_version.get((alias, version))
        return Ok(self._storage[key] if key is not None else None)

    def values(self) -> List[V]:
        """Every value currently stored, in no particular order -- a
        concrete-only convenience (like get_by_id/etc.) for a caller that
        needs to enumerate everything it knows about, e.g. the replication
        loop diffing every registered DataRecord against peers."""
        return list(self._storage.values())
