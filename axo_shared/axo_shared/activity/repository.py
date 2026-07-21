from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import deque
from typing import Deque, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class Repository(Generic[T], ABC):
    """Minimal query-capable persistence abstraction -- in-memory now
    (InMemoryRepository below), a real backend (e.g. Mongo) implementing the
    exact same interface later. Deliberately separate from StorageBackend
    (core/storage/backend.py): that abstraction is pure key-value put/get,
    suited to registries/results; this one is for an activity/audit feed,
    which genuinely wants query-by-criteria (list_recent, list_by_function_id)
    that key-value lookup alone can't express.
    """

    @abstractmethod
    def save(self, entity: T) -> None:
        """Adds one entity. Entities are treated as immutable/append-only --
        saving under an id that already exists is not an update contract
        any current caller relies on."""

    @abstractmethod
    def get(self, id: str) -> Optional[T]:
        """Looks up one entity by id."""

    @abstractmethod
    def list_recent(self, limit: int = 100) -> List[T]:
        """Most-recently-saved entities first, up to limit."""

    @abstractmethod
    def list_by_function_id(self, function_id: str, limit: int = 100) -> List[T]:
        """Most-recently-saved entities for one function_id first, up to limit."""


class InMemoryRepository(Repository[T]):
    """Thread-safe, bounded (FIFO eviction at max_entries) in-memory
    Repository. Not persisted across restarts -- a real backend (Mongo,
    etc.) implementing this same interface is where indexed queries and
    durability would live; list_by_function_id here is a plain linear scan,
    fine at this bound.
    """

    def __init__(self, max_entries: int = 10000) -> None:
        self._entries: Deque = deque(maxlen=max_entries)
        self._by_id: Dict[str, T] = {}
        self._lock = threading.Lock()

    def save(self, entity: T) -> None:
        with self._lock:
            if self._entries.maxlen is not None and len(self._entries) >= self._entries.maxlen:
                oldest = self._entries[0]  # about to be evicted by the append below
                self._by_id.pop(oldest.id, None)
            self._entries.append(entity)
            self._by_id[entity.id] = entity

    def get(self, id: str) -> Optional[T]:
        with self._lock:
            return self._by_id.get(id)

    def list_recent(self, limit: int = 100) -> List[T]:
        with self._lock:
            items = list(self._entries)
        return list(reversed(items))[:limit]

    def list_by_function_id(self, function_id: str, limit: int = 100) -> List[T]:
        with self._lock:
            items = list(self._entries)
        matched = [e for e in reversed(items) if getattr(e, "function_id", None) == function_id]
        return matched[:limit]
