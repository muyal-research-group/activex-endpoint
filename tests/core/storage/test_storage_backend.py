from typing import Dict, Optional

import pytest
from option import Ok, Result

from axo_endpoint.core.storage import StorageBackend, StorageError, StorageKey


def test_storage_backend_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        StorageBackend()


class _FakeBackend(StorageBackend[str]):
    """Trivial in-memory implementation used only to exercise the contract."""

    def __init__(self):
        self._by_id_version: Dict[tuple, str] = {}
        self._by_alias_version: Dict[tuple, str] = {}

    def put(self, key: StorageKey, value: str) -> Result[str, StorageError]:
        if key.version is not None:
            self._by_id_version[(key.id, key.version)] = value
        if key.alias and key.version is not None:
            self._by_alias_version[(key.alias, key.version)] = value
        return Ok(key.id)

    def get(self, key: StorageKey) -> Result[Optional[str], StorageError]:
        if key.alias and key.version is not None:
            return self.get_by_alias_version(key.alias, key.version)
        if key.version is not None:
            return self.get_by_id_version(key.id, key.version)
        if key.alias:
            return self.get_by_alias(key.alias)
        return self.get_by_id(key.id)

    def exists(self, key: StorageKey) -> Result[bool, StorageError]:
        result = self.get(key)
        return Ok(result.unwrap() is not None)

    def get_by_id(self, id: str) -> Result[Optional[str], StorageError]:
        versions = [v for (i, v) in self._by_id_version if i == id]
        if not versions:
            return Ok(None)
        latest = max(versions)
        return Ok(self._by_id_version[(id, latest)])

    def get_by_id_version(self, id: str, version: int) -> Result[Optional[str], StorageError]:
        return Ok(self._by_id_version.get((id, version)))

    def get_by_alias(self, alias: str) -> Result[Optional[str], StorageError]:
        versions = [v for (a, v) in self._by_alias_version if a == alias]
        if not versions:
            return Ok(None)
        latest = max(versions)
        return Ok(self._by_alias_version[(alias, latest)])

    def get_by_alias_version(self, alias: str, version: int) -> Result[Optional[str], StorageError]:
        return Ok(self._by_alias_version.get((alias, version)))


@pytest.fixture
def backend():
    backend = _FakeBackend()
    backend.put(StorageKey(id="k1", version=1, alias="alpha"), "v1")
    backend.put(StorageKey(id="k1", version=2, alias="alpha"), "v2")
    return backend


def test_put_then_get_round_trip(backend):
    result = backend.get(StorageKey(id="k1", version=1))
    assert result.is_ok
    assert result.unwrap() == "v1"


def test_missing_key_returns_ok_none_not_err(backend):
    result = backend.get_by_id("missing")
    assert result.is_ok
    assert result.unwrap() is None


def test_exists_true_and_false(backend):
    assert backend.exists(StorageKey(id="k1", version=1)).unwrap() is True
    assert backend.exists(StorageKey(id="missing")).unwrap() is False


def test_get_by_id_returns_latest_version(backend):
    assert backend.get_by_id("k1").unwrap() == "v2"


def test_get_by_id_version_returns_specific_version(backend):
    assert backend.get_by_id_version("k1", 1).unwrap() == "v1"
    assert backend.get_by_id_version("k1", 2).unwrap() == "v2"


def test_get_by_alias_returns_latest_version(backend):
    assert backend.get_by_alias("alpha").unwrap() == "v2"


def test_get_by_alias_version_returns_specific_version(backend):
    assert backend.get_by_alias_version("alpha", 1).unwrap() == "v1"
