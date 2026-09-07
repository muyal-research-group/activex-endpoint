import os

import pytest

from axo_endpoint.core.storage import FilesystemStorageBackend, FsKey, StoragePathTraversalError


def test_put_then_get_round_trips(tmp_path):
    backend = FilesystemStorageBackend(root=str(tmp_path))
    assert backend.put(FsKey(path="a.bin"), b"hello").is_ok
    result = backend.get(FsKey(path="a.bin"))
    assert result.is_ok
    assert result.unwrap() == b"hello"


def test_get_missing_returns_ok_none_not_err(tmp_path):
    # Deliberate contract change from FilesystemBlobBackend.read(), which
    # returned Err(IONotFoundError): StorageBackend.get() must follow the
    # "no value found is not an error" contract already used by
    # InMemoryStorageBackend, so callers that need read()-must-fail-loudly
    # semantics (dataio.read) translate this themselves.
    backend = FilesystemStorageBackend(root=str(tmp_path))
    result = backend.get(FsKey(path="missing.bin"))
    assert result.is_ok
    assert result.unwrap() is None


def test_put_creates_nested_directories(tmp_path):
    backend = FilesystemStorageBackend(root=str(tmp_path))
    assert backend.put(FsKey(path="nested/dir/file.bin"), b"x").is_ok
    assert os.path.isfile(tmp_path / "nested" / "dir" / "file.bin")


def test_put_is_atomic_no_temp_file_left_behind(tmp_path):
    backend = FilesystemStorageBackend(root=str(tmp_path))
    assert backend.put(FsKey(path="atomic.bin"), b"x" * 1000).is_ok
    remaining = os.listdir(tmp_path)
    assert remaining == ["atomic.bin"]


def test_exists_true_and_false(tmp_path):
    backend = FilesystemStorageBackend(root=str(tmp_path))
    backend.put(FsKey(path="present.bin"), b"x")
    assert backend.exists(FsKey(path="present.bin")).unwrap() is True
    assert backend.exists(FsKey(path="absent.bin")).unwrap() is False


@pytest.mark.parametrize("path", ["../escape.bin", "../../etc/passwd", "/etc/passwd"])
def test_path_traversal_is_rejected(tmp_path, path):
    backend = FilesystemStorageBackend(root=str(tmp_path))
    result = backend.put(FsKey(path=path), b"x")
    assert result.is_err
    assert isinstance(result.unwrap_err(), StoragePathTraversalError)


def test_delete_removes_file(tmp_path):
    backend = FilesystemStorageBackend(root=str(tmp_path))
    backend.put(FsKey(path="a.bin"), b"hello")
    assert backend.delete(FsKey(path="a.bin")).is_ok
    assert backend.get(FsKey(path="a.bin")).unwrap() is None
    assert not os.path.isfile(tmp_path / "a.bin")


def test_delete_missing_file_is_not_an_error(tmp_path):
    backend = FilesystemStorageBackend(root=str(tmp_path))
    result = backend.delete(FsKey(path="missing.bin"))
    assert result.is_ok


def test_symlink_escape_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"secret")
    (root / "escape").symlink_to(outside, target_is_directory=True)

    backend = FilesystemStorageBackend(root=str(root))
    result = backend.get(FsKey(path="escape/secret.bin"))
    assert result.is_err
    assert isinstance(result.unwrap_err(), StoragePathTraversalError)
