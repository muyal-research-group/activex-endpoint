import pytest
from option import Some, NONE
from axo.core.models import MetadataX
from axo_endpoint.store.models import MetadataKey
from axo_endpoint.caching import Cache, LRU, LFU
from axo_endpoint.store import SimpleStore,CachedMetadataStore
# from e import MetadataStore, LocalKVStore, CachedMetadataStore


# ----------------------------
# Fixtures
# ----------------------------


@pytest.fixture
def metadata_store():
    store = SimpleStore()

    # Version 1 of object k1 with alias "alpha"
    m1 = MetadataX(
        axo_module="mod_a",
        axo_class_name="ClsA",
        axo_version=1,
        axo_alias="alpha",
        axo_key="k1",
    )
    store.put(MetadataKey(id="k1", version=1, alias="alpha"), m1)

    # Version 2 of object k1 (latest)
    m2 = MetadataX(
        axo_module="mod_a",
        axo_class_name="ClsA",
        axo_version=2,
        axo_alias="alpha",
        axo_key="k1",
    )
    store.put(MetadataKey(id="k1", version=2, alias="alpha1"), m2)

    # Object k2 with no alias
    m3 = MetadataX(
        axo_module="mod_b",
        axo_class_name="ClsB",
        axo_version=1,
        axo_key="k2",
    )
    store.put(MetadataKey(id="k2", version=1), m3)

    return store


# ----------------------------
# MetadataStore tests
# ----------------------------

def test_get_by_key_latest(metadata_store):
    res = metadata_store.get_by_key("k1")
    assert res.axo_alias == "alpha1" 


def test_get_by_id_version(metadata_store):
    res = metadata_store.get_by_id_version("k1", 1)
    assert res.axo_alias == "alpha"


def test_get_by_alias_latest(metadata_store):
    res = metadata_store.get_by_alias("alpha")
    assert res.axo_version == 1


def test_get_by_alias_version(metadata_store):
    res = metadata_store.get_by_alias_version("alpha", 1)
    assert res.axo_key == "k1"


def test_missing_values_return_none(metadata_store):
    assert metadata_store.get_by_key("missing") is None
    assert metadata_store.get_by_id_version("k1", 999) is None
    assert metadata_store.get_by_alias("missing") is None
    assert metadata_store.get_by_alias_version("alpha", 999) is None


# ----------------------------
# Cache + LRU / LFU tests
# ----------------------------

def test_lru_eviction():
    cache = Cache.lru(capacity=2)
    cache.put("a", "A")
    cache.put("b", "B")
    cache.get("a")       # make 'a' most recently used
    cache.put("c", "C")  # should evict 'b'
    assert "a" in cache.cache
    assert "c" in cache.cache
    assert "b" not in cache.cache


def test_lfu_eviction():
    cache = Cache.lfu(capacity=2)
    cache.put("a", "A")
    cache.put("b", "B")
    cache.get("a")       # freq(a)=2, freq(b)=1
    cache.put("c", "C")  # should evict 'b'
    assert "a" in cache.cache
    assert "c" in cache.cache
    assert "b" not in cache.cache


# ----------------------------
# CachedMetadataStore tests
# ----------------------------

def test_cached_metadata_store_hits(metadata_store):
    cached = CachedMetadataStore(metadata_store, Cache.lru(capacity=2))

    # first call populates cache
    res1 = cached.get_by_key("k1")
    # second call should hit cache
    res2 = cached.get_by_key("k1")

    assert res1 is res2  # same object ref
    assert res1.content == "data2"


def test_cached_metadata_store_eviction(metadata_store):
    cached = CachedMetadataStore(metadata_store, Cache.lru(capacity=1))
    res1 = cached.get_by_key("k1")
    assert res1.content == "data2"

    # cache capacity=1, next call evicts previous
    res2 = cached.get_by_key("k2")
    assert res2.content == "data3"
    assert "id|k1" not in cached.cache.cache
