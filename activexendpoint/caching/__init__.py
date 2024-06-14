from typing import Dict,Any
from abc import ABC,abstractmethod
import heapq
from collections import OrderedDict

class EvictionPolicy(ABC):

    # @abstractmethod
    def attach_cache(self, cache:Dict[str, memoryview]):
        self.cache = cache
        self.data = {}

    @abstractmethod
    def access(self, key):
        raise NotImplementedError
    
    @abstractmethod
    def evict(self):
        raise NotImplementedError

class Cache:
    def __init__(self, capacity:int, eviction_policy:EvictionPolicy):
        self.capacity = capacity
        self.eviction_policy = eviction_policy
        self.cache:Dict[str, memoryview] = {}
        self.eviction_policy.attach_cache(self)

    @staticmethod
    def lru(capacity:int=1000):
        return Cache(
            capacity=capacity,
            eviction_policy=LRU()
        )
    @staticmethod
    def lfu(capacity:int=1000):
        return Cache(
            capacity=capacity,
            eviction_policy=LFU()
        )

    def get(self, key:str):
        if key in self.cache:
            self.eviction_policy.access(key)
            return self.cache[key]
        return None

    def put(self, key:str, value:memoryview):
        if key not in self.cache and len(self.cache) >= self.capacity:
            evict_key = self.eviction_policy.evict()
            if evict_key:
                self.cache.pop(evict_key)
        self.cache[key] = value
        self.eviction_policy.access(key)

    def __repr__(self):
        return f"{self.cache}"

class LRU(EvictionPolicy):
    def __init__(self):
        self.order = OrderedDict()

    def access(self, key:str):
        if key in self.order:
            self.order.move_to_end(key)
        else:
            self.order[key] = True

    def evict(self):
        oldest = next(iter(self.order))
        del self.order[oldest]
        return oldest

class LFU(EvictionPolicy):
    def __init__(self):
        self.freq:Dict[str,float] = {}
        self.min_heap = []
        self.index = 0

    def access(self, key:str):
        current_freq = self.freq.setdefault(key, 0)
        self.freq[key] = current_freq+1

        heapq.heappush(self.min_heap, (self.freq[key], self.index, key))
        self.index += 1

    def evict(self):
        while self.min_heap:
            freq, _, key = heapq.heappop(self.min_heap)
            if self.freq[key] == freq:
                del self.freq[key]
                return key
        return None

