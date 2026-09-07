from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import List, Optional

from option import Err, Ok, Result

from axo_endpoint.core.storage.backend import Key, StorageBackend, StorageError


class StoragePathTraversalError(StorageError):
    """A key's path resolved outside the backend's root directory."""

    code = 8001
    name = "STORAGE_PATH_TRAVERSAL"


class StorageBackendIOError(StorageError):
    """An OSError occurred while reading or writing the underlying file."""

    code = 8002
    name = "STORAGE_BACKEND_IO_ERROR"


@dataclass(frozen=True)
class FsKey(Key):
    """Addresses a value by relative filesystem path. to_str/from_str are an
    identity mapping, since the path itself is already the wire-safe string
    IORef.location for kind="fs"."""

    path: str

    def to_str(self) -> str:
        return self.path

    @staticmethod
    def from_str(s: str) -> "FsKey":
        return FsKey(path=s)


class FilesystemStorageBackend(StorageBackend[FsKey, bytes]):
    """StorageBackend rooted at a local directory.

    Every key is resolved and checked for containment under ``root`` via
    ``os.path.realpath``/``os.path.commonpath`` (not ``str.startswith``, which
    would be fooled by a sibling directory sharing the root as a string
    prefix) -- this also catches a symlink planted inside root that points
    outside it, since realpath follows symlinks before the check.
    """

    def __init__(self, root: str) -> None:
        self._root = os.path.realpath(root)
        os.makedirs(self._root, exist_ok=True)

    def _resolve(self, key: FsKey) -> Result[str, StorageError]:
        candidate = os.path.realpath(os.path.join(self._root, key.path))
        if os.path.commonpath([candidate, self._root]) != self._root:
            return Err(StoragePathTraversalError(
                f"path {key.path!r} escapes the storage root", context={"path": key.path},
            ))
        return Ok(candidate)

    def put(self, key: FsKey, value: bytes) -> Result[str, StorageError]:
        path_result = self._resolve(key)
        if path_result.is_err:
            return Err(path_result.unwrap_err())
        path = path_result.unwrap()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # Write to a sibling temp file then os.replace() onto the final
            # path, so a concurrent get() never observes a partially-written
            # file -- required for the blob-replication follower commit to be
            # atomic. Same directory guarantees same filesystem, so
            # os.replace is atomic on POSIX.
            fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path))
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(value)
                os.replace(tmp_path, path)
            except OSError:
                os.unlink(tmp_path)
                raise
            return Ok(key.path)
        except OSError as exc:
            return Err(StorageBackendIOError(str(exc), context={"path": key.path}))

    def get(self, key: FsKey) -> Result[Optional[bytes], StorageError]:
        path_result = self._resolve(key)
        if path_result.is_err:
            return Err(path_result.unwrap_err())
        path = path_result.unwrap()
        try:
            with open(path, "rb") as f:
                return Ok(f.read())
        except FileNotFoundError:
            return Ok(None)
        except OSError as exc:
            return Err(StorageBackendIOError(str(exc), context={"path": key.path}))

    def exists(self, key: FsKey) -> Result[bool, StorageError]:
        path_result = self._resolve(key)
        if path_result.is_err:
            return Err(path_result.unwrap_err())
        return Ok(os.path.isfile(path_result.unwrap()))

    def list_versions(self, id: str) -> Result[List[FsKey], StorageError]:
        """Interface completeness only -- functions (the only current caller
        of this method) never use this backend, and FsKey's flat opaque-path
        keys have no built-in id/version structure the way StorageKey does.
        Treats `id` as a directory prefix: every file found under root/id/
        becomes one FsKey. Untested by real use."""
        prefix_result = self._resolve(FsKey(path=id))
        if prefix_result.is_err:
            return Err(prefix_result.unwrap_err())
        prefix = prefix_result.unwrap()
        if not os.path.isdir(prefix):
            return Ok([])
        keys: List[FsKey] = []
        for dirpath, _dirnames, filenames in os.walk(prefix):
            for filename in filenames:
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, self._root)
                keys.append(FsKey(path=rel))
        return Ok(keys)

    def delete(self, key: FsKey) -> Result[None, StorageError]:
        path_result = self._resolve(key)
        if path_result.is_err:
            return Err(path_result.unwrap_err())
        try:
            os.remove(path_result.unwrap())
        except FileNotFoundError:
            pass
        except OSError as exc:
            return Err(StorageBackendIOError(str(exc), context={"path": key.path}))
        return Ok(None)
