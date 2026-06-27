from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

from option import Result

from axo_endpoint.core.errors import AxoError

V = TypeVar("V")


@dataclass(frozen=True)
class StorageKey:
    """Identifies a stored value: an id, with an optional version and alias."""

    id: str
    version: Optional[int] = None
    alias: Optional[str] = None
    @staticmethod
    def from_str(x: str) -> 'StorageKey':
        """Parse a StorageKey from a string of the form "id[:version][:alias]".

        The version and alias are optional, but if both are present, the version must come first.
        """
        parts = x.split(":")
        if len(parts) == 1:
            return StorageKey(id=parts[0])
        elif len(parts) == 2:
            try:
                version = int(parts[1])
                return StorageKey(id=parts[0], version=version)
            except ValueError:
                return StorageKey(id=parts[0], alias=parts[1])
        elif len(parts) == 3:
            version = int(parts[1])
            return StorageKey(id=parts[0], version=version, alias=parts[2])
        else:
            raise ValueError(f"Invalid StorageKey string: {x}")


class StorageError(AxoError):
    """Base class for all StorageBackend failure modes."""

    code = 4003
    name = "STORAGE_ERROR"


class StorageBackend(ABC, Generic[V]):
    """Saves and looks up values by key. A lookup that finds nothing returns "no value" rather than an error."""

    @abstractmethod
    def put(self, key: StorageKey, value: V) -> Result[str, StorageError]:
        """Store value under key; returns the canonical id on success."""

    @abstractmethod
    def get(self, key: StorageKey) -> Result[Optional[V], StorageError]:
        """Look up by key (id, optional version, optional alias)."""

    @abstractmethod
    def exists(self, key: StorageKey) -> Result[bool, StorageError]:
        """Check existence without retrieving the value."""

    @abstractmethod
    def get_by_id(self, id: str) -> Result[Optional[V], StorageError]:
        """Return the latest version stored under this id."""

    @abstractmethod
    def get_by_id_version(self, id: str, version: int) -> Result[Optional[V], StorageError]:
        """Return a specific version stored under this id."""

    @abstractmethod
    def get_by_alias(self, alias: str) -> Result[Optional[V], StorageError]:
        """Return the latest version stored under this alias."""

    @abstractmethod
    def get_by_alias_version(self, alias: str, version: int) -> Result[Optional[V], StorageError]:
        """Return a specific version stored under this alias."""
