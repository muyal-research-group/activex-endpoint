from abc import ABC, abstractmethod
from option import Option,Some,NONE
from typing import Dict,Any
class KVStore(ABC):
    @abstractmethod
    def put(self,key:str,value:Any)->str:
        pass

    @abstractmethod
    def get(self,key:str)->Option[Any]:
        pass

    @abstractmethod
    def exists(self,key:str)->bool:
        pass


class LocalKVStore(KVStore):
    def __init__(self):
        self.__db:Dict[str,Any] = {}

    def put(self, key: str, value: Any) -> str:
        self.__db.setdefault(key,value)

    def get(self, key: str)->Option[Any]:
        res = self.__db.get(key,-1)
        if res == -1:
            return NONE
        return Some(res)
    
    def exists(self, key: str) -> bool:
        return key in self.__db