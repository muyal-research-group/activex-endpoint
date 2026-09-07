from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, List, Optional, TypeVar

from option import Result

from axo_endpoint.core.errors import AxoError

V = TypeVar("V")


class Key(ABC):
    """Identifies a value in a StorageBackend. Each backend defines its own
    concrete Key shape (StorageKey for id/version/alias catalogs, FsKey for
    filesystem paths, etc) and must be able to round-trip it through a plain
    string, since keys sometimes need to travel as a wire-level string (e.g.
    IORef.location)."""

    @abstractmethod
    def to_str(self) -> str:
        """Encode this key as a string that from_str can parse back."""

    @staticmethod
    @abstractmethod
    def from_str(s: str) -> "Key":
        """Parse a key back out of the string to_str produced."""


@dataclass(frozen=True)
class StorageKey(Key):
    """Identifies a stored value: an id, with an optional version and alias."""

    id: str
    version: Optional[int] = None
    alias: Optional[str] = None

    def to_str(self) -> str:
        """Encode as "id[:version][:alias]", the inverse of from_str.

        Note: the (version=None, alias=set) case round-trips ambiguously --
        from_str tries int(parts[1]) first, so an alias that happens to look
        like an integer would be reparsed as a version. No current caller
        produces that combination (StorageKey is always built with id+version
        set together), so this is left as-is rather than fixed.
        """
        if self.version is not None and self.alias is not None:
            return f"{self.id}:{self.version}:{self.alias}"
        if self.version is not None:
            return f"{self.id}:{self.version}"
        if self.alias is not None:
            return f"{self.id}:{self.alias}"
        return self.id

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
    """Base class for all StorageBackend failure modes.

    Not a base/subclass of errors.StorageFailureError (code 4003) -- that's a
    deliberate sibling used by handlers to wrap a raw StorageError's message
    into a wire-safe domain error at the CommandResult boundary, the same way
    core.dataio.protocol wraps StorageError into a DataIOError. Kept as a
    distinct code range (8xxx) so the two no longer collide.
    """

    code = 8000
    name = "STORAGE_ERROR"


K = TypeVar("K", bound=Key)


class StorageBackend(ABC, Generic[K, V]):
    """Saves and looks up values by key. A lookup that finds nothing returns "no value" rather than an error."""

    @abstractmethod
    def put(self, key: K, value: V) -> Result[str, StorageError]:
        """Store value under key; returns the canonical id on success."""

    @abstractmethod
    def get(self, key: K) -> Result[Optional[V], StorageError]:
        """Look up by key."""

    @abstractmethod
    def exists(self, key: K) -> Result[bool, StorageError]:
        """Check existence without retrieving the value."""

    @abstractmethod
    def delete(self, key: K) -> Result[None, StorageError]:
        """Remove the value stored under key, if any. Not an error if nothing was there."""

    @abstractmethod
    def list_versions(self, id: str) -> Result[List[K], StorageError]:
        """Every key currently stored under this id, across all versions --
        used to compute the next version to assign for a given id without
        the caller needing to know a backend's internal indexing."""
