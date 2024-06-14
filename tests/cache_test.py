import unittest as UT
from activexendpoint.caching import Cache, LRU

class CachingTest(UT.TestCase):

    def test_cache(self):
       cache  =Cache.lru(capacity=100)
       cache.put(key="x1",value=memoryview(b"HGola"))
       cache.put(key="x2",value=memoryview(b"HGolax2"))
       print(bytearray(cache.get("x2") ))


if __name__ == "__main__":
    UT.main()