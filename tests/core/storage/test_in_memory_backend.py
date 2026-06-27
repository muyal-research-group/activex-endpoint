import pytest

from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey


@pytest.fixture
def backend():
    backend = InMemoryStorageBackend()

    # Version 1 of object k1 with alias "alpha"
    backend.put(StorageKey(id="k1", version=1, alias="alpha"), "data1")
    # Version 2 of object k1 (latest), under a different alias
    backend.put(StorageKey(id="k1", version=2, alias="alpha1"), "data2")
    # Object k2 with no alias
    backend.put(StorageKey(id="k2", version=1), "data3")

    return backend


def test_get_by_id_returns_latest_version(backend):
    result = backend.get_by_id("k1")
    assert result.is_ok
    assert result.unwrap() == "data2"


def test_get_by_id_version_returns_specific_version(backend):
    result = backend.get_by_id_version("k1", 1)
    assert result.is_ok
    assert result.unwrap() == "data1"


def test_get_by_alias_returns_matching_version(backend):
    result = backend.get_by_alias("alpha")
    assert result.is_ok
    assert result.unwrap() == "data1"


def test_get_by_alias_version_returns_specific_version(backend):
    result = backend.get_by_alias_version("alpha1", 2)
    assert result.is_ok
    assert result.unwrap() == "data2"


def test_get_resolves_by_full_key(backend):
    assert backend.get(StorageKey(id="k1", version=1)).unwrap() == "data1"
    assert backend.get(StorageKey(id="k1", alias="alpha1", version=2)).unwrap() == "data2"
    assert backend.get(StorageKey(id="k2")).unwrap() == "data3"


def test_missing_values_return_ok_none_not_err(backend):
    assert backend.get_by_id("missing").unwrap() is None
    assert backend.get_by_id_version("k1", 999).unwrap() is None
    assert backend.get_by_alias("missing").unwrap() is None
    assert backend.get_by_alias_version("alpha", 999).unwrap() is None

    for result in (
        backend.get_by_id("missing"),
        backend.get_by_id_version("k1", 999),
        backend.get_by_alias("missing"),
        backend.get_by_alias_version("alpha", 999),
    ):
        assert result.is_ok
        assert result.is_err is False


def test_exists_true_and_false(backend):
    assert backend.exists(StorageKey(id="k1", version=1)).unwrap() is True
    assert backend.exists(StorageKey(id="missing")).unwrap() is False


def test_put_returns_ok_with_id():
    backend = InMemoryStorageBackend()
    result = backend.put(StorageKey(id="k3", version=1), "data4")
    assert result.is_ok
    assert result.unwrap() == "k3"
