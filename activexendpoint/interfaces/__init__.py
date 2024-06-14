from typing import Dict,Callable, Any,List
import string
from nanoid import generate as nanoid 
AnyFunctionType = Callable[..., any]
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
        if self.operation == "PUT.METADATA":
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
    def get_sink_keys(self)->List[str]:
        return self.__get_state().get("sink_keys",[])
        # retu
        # keys = list(filter(lambda x: len(x)>0 or not x =="",keys_str.split(self.get_separator())))
        # if len(keys) == 0:
            # return [self.get_sink_key()]
        # else: 
            # return keys