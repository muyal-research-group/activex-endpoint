from abc import ABC, abstractmethod
from option import Option,Some,NONE
from typing import Dict,Tuple,Set,Optional,List
from axo.core.models import MetadataX
from axo_endpoint.store.models import MetadataKey
from axo_endpoint.caching import Cache

class KVStore(ABC):
    """Abstract contract for all key-value/metadata stores."""

    # Basic CRUD
    @abstractmethod
    def put(self, key: MetadataKey, value: MetadataX) -> str:
        pass

    @abstractmethod
    def get(self, key: MetadataKey) -> Option[MetadataX]:
        pass

    @abstractmethod
    def exists(self, key: MetadataKey) -> bool:
        pass

    # Rich queries
    @abstractmethod
    def get_by_key(self, id: str) -> Optional[MetadataX]:
        pass

    @abstractmethod
    def get_by_id_version(self, id: str, version: int) -> Optional[MetadataX]:
        pass

    @abstractmethod
    def get_by_alias(self, alias: str) -> Optional[MetadataX]:
        pass

    @abstractmethod
    def get_by_alias_version(self, alias: str, version: int) -> Optional[MetadataX]:
        pass

class SimpleStore(KVStore):
    def __init__(self):
        self._storage: Dict[MetadataKey, MetadataX] = {}
        self._by_id_version: Dict[Tuple[str, int], MetadataKey] = {}
        self._by_alias_version: Dict[Tuple[str, int], MetadataKey] = {}

    def put(self, key: MetadataKey, value: MetadataX) -> str:
        self._storage[key] = value
        if key.version is not None:
            self._by_id_version[(key.id, key.version)] = key
        if key.alias and key.version is not None:
            self._by_alias_version[(key.alias, key.version)] = key
        return key.id

    def get(self, key: MetadataKey) -> Option[MetadataX]:
        if key.version is None and key.alias is None:
            res = self.get_by_key(key.id)
        elif key.version is not None and key.alias is None:
            res = self.get_by_id_version(key.id, key.version)
        elif key.alias and key.version is None:
            res = self.get_by_alias(key.alias)
        elif key.alias and key.version is not None:
            res = self.get_by_alias_version(key.alias, key.version)
        else:
            res = None
        return Some(res) if res else NONE

    def exists(self, key: MetadataKey) -> bool:
        return key in self._storage

    def get_by_key(self, id: str) -> Optional[MetadataX]:
        keys = [k for k in self._storage if k.id == id]
        if not keys:
            return None
        latest = max(keys, key=lambda k: k.version or 0)
        return self._storage[latest]

    def get_by_id_version(self, id: str, version: int) -> Optional[MetadataX]:
        key = self._by_id_version.get((id, version))
        return self._storage[key] if key else None

    def get_by_alias(self, alias: str) -> Optional[MetadataX]:
        keys = [k for k in self._storage if k.alias == alias]
        if not keys:
            return None
        latest = max(keys, key=lambda k: k.version or 0)
        return self._storage[latest]

    def get_by_alias_version(self, alias: str, version: int) -> Optional[MetadataX]:
        key = self._by_alias_version.get((alias, version))
        return self._storage[key] if key else None


class CachedMetadataStore:
    def __init__(self, store: KVStore, cache: Cache):
        self.store = store
        self.cache = cache

    def _cache_key(self, *args) -> str:
        return "|".join(args)

    def get_by_key(self, id: str)->Optional[MetadataX]:
        key = self._cache_key("id", id)
        cached = self.cache.get(key)
        if cached:
            return cached
        res = self.store.get_by_key(id)
        if res:
            self.cache.put(key, res)
        return res

    def get_by_id_version(self, id: str, version: str)->Optional[MetadataX]:
        key = self._cache_key("idv", id, version)
        cached = self.cache.get(key)
        if cached:
            return cached
        res = self.store.get_by_id_version(id, version)
        if res:
            self.cache.put(key, res)
        return res

    def get_by_alias(self, alias: str, latest: bool = True)->Option[MetadataX]:
        key = self._cache_key("alias", alias, "latest" if latest else "all")
        cached = self.cache.get(key)
        if cached:
            return cached
        res = self.store.get_by_alias(alias, latest)
        if res:
            self.cache.put(key, res)
        return res

    def get_by_alias_version(self, alias: str, version: str)->Optional[MetadataX]:
        key = self._cache_key("aliasv", alias, version)
        cached = self.cache.get(key)
        if cached:
            return cached
        res = self.store.get_by_alias_version(alias, version)
        if res:
            self.cache.put(key, res)
        return res
