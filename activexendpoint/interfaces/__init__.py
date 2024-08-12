from typing import Dict,Callable, Any,List
import string
from nanoid import generate as nanoid 
import humanfriendly as HF
import time as T
import asyncio
AnyFunctionType = Callable[..., any]

class Heater:
    def __init__(self,max_idle_time:str = "1h"):
        self.start_time = T.time()
        self.last_invocation = T.time()
        self.max_idle_time = HF.parse_timespan(max_idle_time)
        self.envent = asyncio.Event()
        self.q = []
    def warm(self,task_id:str=""):
        self.q.append(task_id)
        self.last_invocation = T.time()
    def is_cold(self)->bool:
        
        return (T.time() - self.last_invocation)  >= self.max_idle_time
class Task(object):
    def __init__(self,topic:str, operation:str, metadata:Dict[str,Any], f:AnyFunctionType,fargs:list= [],fkwargs:dict = {}):
        self.task_id = nanoid()
        self.topic  = topic
        self.operation = operation
        self.metadata= metadata
        self. f = f 
        self.fargs = fargs
        self.fkwargs= fkwargs
        # self.max_workers = 
        self.endpoint_id = ""
        self.axo_bucket_id = ""
        self.sink_bucket_id = ""
        self.source_bucket_id = ""
        self.output_key = ""
        self.separator = ";"
    
    # def __str
    def __get_state(self):
        if self.operation == "PUT.METADATA" or self.operation=="MW":
            return self.metadata
        else:
            return self.fkwargs
    def get_dependencies(self)->List[str]:
        deps_str:List[str] = self.__get_state().get("dependencies",[])
        return deps_str
        # deps = deps_str.split(self.get_separator())
        # return list(filter(lambda x: len(x)>0,deps))
    
    def get_separator(self)->str:
        return self.__get_state().get("separator",self.separator)
    
    def get_endpoint_id(self)->str:
        return self.__get_state().get("endpoint_id","activex-endpoint-{}".format(nanoid(alphabet=string.ascii_lowercase+string.digits, size=5)))
    
    def get_sink_bucket_id(self)->str:
        return self.__get_state().get("sink_bucket_id", nanoid(alphabet=string.ascii_lowercase + string.digits,size=12))

    def get_axo_bucket_id(self)->str:
        return self.__get_state().get("axo_bucket_id", nanoid(alphabet=string.ascii_lowercase+string.digits))
    def get_axo_key(self)->str:
        return self.__get_state().get("axo_key", nanoid(alphabet=string.ascii_lowercase+string.digits))
    # ___________________________________________
    def get_source_bucket_id(self)->str:
        return self.__get_state().get("source_bucket_id", nanoid(alphabet=string.ascii_lowercase+string.digits))
    
    # def get_source_key(self)->str:
        # return self.__get_state().get("source_key", "")

    def get_source_keys(self)->List[str]:
        return self.__get_state().get("source_keys", [])
    
    def is_bucket_main_source(self)->bool:
        return self.get_source_key() == "" and len(self.get_source_keys() ) ==0
    
    # def get_sink_key(self)->str:
        # return self.__get_state().get("sink_key", nanoid(alphabet=string.ascii_lowercase+string.digits))
    # def get_sink_keys(self)->List[str]:
        # return self.__get_state().get("sink_keys",[])
        # retu
        # keys = list(filter(lambda x: len(x)>0 or not x =="",keys_str.split(self.get_separator())))
        # if len(keys) == 0:
            # return [self.get_sink_key()]
        # else: 
            # return keys