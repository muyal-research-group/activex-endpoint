from abc import ABC,abstractmethod
from activex import ActiveX
from option import Result,Err,Ok
from typing import Tuple,Any
import cloudpickle as CP
import json as J
from activexendpoint.dummy import add_dummy_module
import types
class Serde(ABC):
    def __init__(self):
        pass
    @abstractmethod
    def serialize(self,axo:ActiveX)->Result[bytes, Exception]:
        pass
    @abstractmethod
    def deserialize(self,x:bytes)->Result[ActiveX, Exception]:
        pass

class DefaultSerde(Serde):
    def __init__(self):
        super().__init__()
    def serialize(self,axo:ActiveX)->Result[bytes,Exception]:
        try:
            return Ok(axo.to_bytes())
            # return Ok(CP.dumps(axo))
        except Exception as e:
            return Err(e)
    def deserialize(self, x: bytes,**kwargs)->Result[ActiveX, Exception]:
        try:
            original_f:bool = kwargs.get("original_f",False)
            res = ActiveX.get_object_parts(raw_obj= x,original_f=original_f)
            if res.is_err:
                return res
            (attrs, methods, class_def, class_code) = res.unwrap()
            print("ATTRS", attrs)
            instance:ActiveX = class_def()
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
            # return Ok(CP.loads(x))
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
   