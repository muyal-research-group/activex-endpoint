from abc import ABC,abstractmethod
from axo import Axo
from option import Result,Err,Ok
from typing import Tuple,Any
import cloudpickle as CP
import json as J
import types
class Serde(ABC):
    def __init__(self):
        pass
    @abstractmethod
    def serialize_ao(self,axo:Axo)->Result[bytes, Exception]:
        pass
    @abstractmethod
    def deserialize_ao(self,x:bytes)->Result[Axo, Exception]:
        pass
    @abstractmethod
    def serialize(self,x:Any)->Result[bytes, Exception]:
        pass
    @abstractmethod
    def deserialize(self,x:bytes)->Result[Any, Exception]:
        pass

class DefaultSerde(Serde):
    def __init__(self):
        super().__init__()
    def serialize(self, x: Any) -> Result[bytes, Exception]:
        try:
            return CP.dumps(x)
        except Exception as e:
            return Err(e)
    def deserialize(self, x: bytes) -> Result[Any, Exception]:
        try:
            return Ok(CP.loads(x))
        except Exception as e:
            return Err(e)
    def serialize_ao(self,axo:Axo)->Result[bytes,Exception]:
        try:
            return Ok(axo.to_bytes())
            # return Ok(CP.dumps(axo))
        except Exception as e:
            return Err(e)
    def deserialize_ao(self, x: bytes,**kwargs)->Result[Axo, Exception]:
        try:
            original_f:bool = kwargs.get("original_f",False)
            res = Axo.get_parts(raw_obj= x)
            print("RES",res)
            if res.is_err:
                return res
            (attrs, methods, class_def, class_code) = res.unwrap()
            # print("ATTRS", attrs)
            instance:Axo = class_def()
            for attr_name, attr_value in attrs.items():
                if attr_name not in ('__class__', '__dict__', '__module__', '__weakref__'):
                    setattr(instance, attr_name, attr_value)
            for method_name, func in methods.items():
                if "original" in dir(func) and original_f:
                    func = func.original
                bound_method = types.MethodType(func, instance)
                if method_name not in ('__class__', '__dict__', '__module__', '__weakref__'):
                    setattr(instance, method_name, bound_method)
            return Ok(instance)
        except Exception as e:
            return Err(e)
    def serialize_fresult(self,result:Any)->Result[Tuple[int, bytes],Exception]:
        try:
            x = J.dumps(result)
            return Ok((0,x.encode()))
        except Exception as e:
            try: 
                x = CP.dumps(result)
                return Ok((1,x))
            except Exception as e:
                return Err(e)
   