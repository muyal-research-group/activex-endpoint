import zmq.asyncio 
import time as T
import os 
# from typing import Callable
import cloudpickle as CP
import json as J
from typing import List,Tuple,Dict,Any,Callable
import logging
import asyncio
from abc import ABC,abstractmethod
from option import Result,Ok,Err,Option,Some,NONE
from activex import ActiveX
from mictlanx.v4.interfaces.responses import GetBytesResponse,GetMetadataResponse
from mictlanx.v4.client import Client
from mictlanx.utils.index import Utils as MictlanXUtils
from nanoid import generate as nanoid
import sys
from pathlib import Path
import types
CODE_REPOSITORY_PATH = os.environ.get("CODE_REPOSITORY_PATH","/home/nacho/Programming/Python/activex-middleware/code")

ERROR_STATUS_INT = -1
number_of_bytes  = 4
# (ERROR_STATUS_INT.bit_length() + 7) // 8 + 1
# print(number_of_bytes)
ERROR_STATUS     = ERROR_STATUS_INT.to_bytes(byteorder="little",length=number_of_bytes,signed=True)
# 
SUCCESS_STATUS_INT = 0
# number_of_bytes    = (SUCCESS_STATUS_INT.bit_length() + 7) // 8
# print(number_of_bytes)
SUCCESS_STATUS     = SUCCESS_STATUS_INT.to_bytes(byteorder="little",length=number_of_bytes,signed=True)


class Dummy:
    def __init__(self, *args, **kwargs):
        self.__dict__['attributes'] = {}
        self.__dict__['methods'] = {}

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, state):
        self.__dict__.update(state)

    def __getattr__(self, name):
        # Provide access to methods
        if name in self.__dict__['methods']:
            return self.__dict__['methods'][name]
        # Provide access to attributes
        if name in self.__dict__['attributes']:
            return self.__dict__['attributes'][name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        if callable(value):
            self.__dict__['methods'][name] = value
        else:
            self.__dict__['attributes'][name] = value
    # def __init__(self, *args, **kwargs):
    #     pass

    # def __getstate__(self):
    #     return {}

    # def __setstate__(self, state):
    #     self.__dict__.update(state)
    
# dummy_module = types.ModuleType("tests.common")
# sys.modules["tests.common"] = dummy_module
# dummy_module.Dog = Dummy

def add_dummy_module(module_path, class_name, dummy_class):
    logger.debug({
        "event":"ADD.MODULE.BEFORE",
        "module":module_path,
        "name":class_name,
        "class":dummy_class,
        "modules":len(sys.modules)
    })
    parts = module_path.split('.')
    # Create and insert parent modules if they don't exist
    for i in range(1, len(parts)):
        parent_module_name = '.'.join(parts[:i])
        previous_index = i -1
        if parent_module_name not in sys.modules:
            parent_module = types.ModuleType(parent_module_name)
            sys.modules[parent_module_name] = parent_module
            # Add the parent module to its own parent if necessary
            if i > 1:
                # part_i_1 = par
                grandparent_module_name = '.'.join(parts[:previous_index ])
                setattr(sys.modules[grandparent_module_name], parts[i-1], parent_module)
    
    # Create the final module and add the dummy class
    module_name = parts[-1]
    final_module = types.ModuleType(module_path)
    setattr(final_module, class_name, dummy_class)
    sys.modules[module_path] = final_module

    # Add the final module to its parent module
    parent_module_path = '.'.join(parts[:-1])
    if parent_module_path:
        setattr(sys.modules[parent_module_path], module_name, final_module)
    logger.debug({
        "event":"ADD.MODULE.AFTER",
        "module":module_path,
        "name":class_name,
        "class":dummy_class,
        "modules":len(sys.modules)
    })

# def add_dummy_module(module_name, class_name, dummy_class):
#     # Create a dummy module
#     dummy_module = types.ModuleType(module_name)
#     # Add the dummy class to the module
#     setattr(dummy_module, class_name, dummy_class)
#     # Insert the dummy module into sys.modules
#     sys.modules[module_name] = dummy_module
#     logger.debug({
#         "event":"ADD_MODULE",
#         "module":module_name,
#         "name":class_name,
#         "class":dummy_class
#     })

# Example usage: Add a dummy module named 'dummy.module' with DummyClass
# add_dummy_module('dummy.module', 'DummyClass', DummyClass)

sys.path.append(CODE_REPOSITORY_PATH)

# print(sys.path)

logger = logging.getLogger(__name__)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.setLevel(logging.DEBUG)

BUCKET_ID = os.environ.get("MICTLANX_BUCKET_ID","activex")
routers = list(MictlanXUtils.routers_from_str(os.environ.get("MICTLANX_ROUTERS","mictlanx-router-0:localhost:60666"), separator=" "))


logger.debug({
    "event":"STATS",
    "sys.path":sys.path
})

mictlanx_client = Client(
    client_id       = os.environ.get("MICTLANX_CLIENT_ID", "activex-mictlanx-0"),
    bucket_id       = BUCKET_ID,
    debug           = bool(int(os.environ.get("MICTLANX_DEBUG","0"))),
    log_interval    = int(os.environ.get("MICTLANX_LOG_INTERVAL","24")),
    log_when        = os.environ.get("MICTLANX_LOG_WHENA","h"),
    log_output_path = os.environ.get("MICTLANX_LOG_OUTPUT_PATH","/log"),
    max_workers     = int(os.environ.get("MICTLANX_MAX_WORKERS","4")),
    routers         =routers
)


context = zmq.asyncio.Context()
pub_sub_socket = context.socket(zmq.SUB)
req_rep_socket = context.socket(zmq.REP)
pub_sub_socket.setsockopt(zmq.SUBSCRIBE,b"activex")

protocol =  os.environ.get("ACTIVEX_PROTOCOL","tcp")
port     = int(os.environ.get("ACTIVEX_PUB_SUB_PORT",16666))
req_rep_port     = int(os.environ.get("ACTIVEX_REQ_REP_PORT",16667))
hostname = os.environ.get("ACTIVEX_HOSTNAME","127.0.0.1")

uri =  hostname if port == -1 else "{}:{}".format(hostname,port)
uri2 =  hostname if port == -1 else "{}:{}".format(hostname,req_rep_port)

# waiting = float(os.environ.get("ACTIVEX_MIDDLEWARE_WAITING_TIME","1"))

pub_sub_socket.connect("{}://{}".format(protocol,uri))
req_rep_socket.bind("{}://{}".format(protocol,uri2))


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
        

local_kv = LocalKVStore()


# Define a type hint for any callable
AnyFunctionType = Callable[..., any]
class Task(object):
    def __init__(self,topic:str, operation:str, metadata:Dict[str,Any], f:AnyFunctionType,fargs:list= [],fkwargs:dict = {}):
        self.topic  = topic
        self.operation = operation
        self.metadata= metadata
        self. f = f 
        self.fargs = fargs
        self.fkwargs= fkwargs


def  from_multipart_to_task(multipart:List[bytes])->Result[Task,Exception]:
    if len(multipart) == 3:
        topic_bytes,op_bytes, metadata_bytes = multipart 
        return Ok(Task(
            topic     = topic_bytes.decode(encoding="utf-8"),
            operation = op_bytes.decode(encoding="utf-8"),
            metadata  = J.loads(metadata_bytes),
            f         = bytearray()
        ))
    if len(multipart) == 4:
        topic_bytes,op_bytes, metadata_bytes, fbytes = multipart 
        return Ok(Task(
            topic     = topic_bytes.decode(encoding="utf-8"),
            operation = op_bytes.decode(encoding="utf-8"),
            metadata  = J.loads(metadata_bytes),
            f         = fbytes 
        ))
    if len(multipart) == 6:
        topic_bytes,op_bytes, metadata_bytes, fbytes,fargs_bytes, fkwargs_bytes = multipart 
        return Ok(Task(
            topic     = topic_bytes.decode(encoding="utf-8"),
            operation = op_bytes.decode(encoding="utf-8"),
            metadata  = J.loads(metadata_bytes),
            f         = CP.loads(fbytes),
            fargs     = CP.loads(fargs_bytes),
            fkwargs   = CP.loads(fkwargs_bytes)
        ))
    return Err(Exception("Multipart request is malformed"))




async def put_metadata(topic:str,operation:str, metadata:Dict[str,Any])->Result[str, Exception]:
    start_time = T.time()
    key = metadata.get("id", -1)
    if key == -1:
        error_obj = {"key":key,"detail":"Malformed request: It does not contain id field."}
        await req_rep_socket.send_multipart([b"activex",b"BAD.REQUEST", J.dumps(error_obj).encode() ])
        logger.error("{} {}".format("BAD.REQUEST",key))
        return Err(Exception(error_obj.get("detail","Uknown error")))
        # continue
    if local_kv.exists(key=key):
        error_obj = {"key":key, "detail":"{} already exists".format(key)}
        await req_rep_socket.send_multipart([b"activex",b"ALREADY.EXISTS", J.dumps(error_obj).encode() ])
        logger.error("{} {}".format("ALREADY.EXISTS",key))
        return Err(Exception(error_obj.get("detail","Uknown error")))
    
    local_kv.put(key=key, value= metadata)
    rt = T.time() - start_time
    logger.info({
        "event":"PUT.METADATA",
        "key":key,
        **metadata,
        "response_time":rt
    })
        # "{} {} {}".format("PUT.METADATA",key,rt))
    return Ok(key)



async def method_execution(_msg:Task)->Result[Any, Exception]:
    start_time = T.time()
    key        = _msg.metadata.get("key",-1)
    if key == -1:
        error_msg = "Key not found in metadata"
        logger.error({
            "msg":error_msg,
            "operation":"METHOD.EXEC"
        })
        await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])
        return Err(Exception(error_msg))
        # continue

    maybe_mictlanx_metadata = local_kv.get(key=key)
    if maybe_mictlanx_metadata.is_none:
        logger.warning({
            "event":"NOT.FOUND",
            "key":key,
        })
        get_metadata_start_time = T.time()
        # Get from MictlanX
        get_metadata_result:Result[GetMetadataResponse, Exception]= mictlanx_client.get_metadata(key=key,bucket_id=BUCKET_ID).result()
        if get_metadata_result.is_err:
            error_msg = "{} not found".format(key)
            logger.error({
                "error":error_msg,
                "key":key
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))

        remote_metadata = get_metadata_result.unwrap()
        logger.info({
            "event":"GET.REMOTE.METADATA",
            "key":key,
            "response_time":T.time() - get_metadata_start_time
        })
        put_metadata_start_time = T.time()
        # Put in metadata
        await put_metadata(topic=_msg.topic,operation=_msg.operation,metadata=remote_metadata.metadata.tags)
        maybe_mictlanx_metadata = Some(remote_metadata.metadata.tags)
    
    local_metadata = maybe_mictlanx_metadata.unwrap()
    module         = local_metadata.get("module",-1)
    name           = local_metadata.get("name",-1)
    add_dummy_module(module, name, Dummy)
    if module == -1 or name == -1:
        error_msg = "module or name attribute not found in tags"
        logger.error({
            "msg":error_msg,
            "key":key,
            "operation":"METHOD.EXEC"
        })
        await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])
        return Err(Exception(error_msg))
        # continue
    
    obj_result_get_response :Result[GetBytesResponse,Exception]= mictlanx_client.get(bucket_id=BUCKET_ID, key=key).result()

    
    if obj_result_get_response.is_err:
        error_msg = "get_to_file failed"
        logger.error({
            "msg":error_msg, 
            "key":key
        })
        await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])
        return Err(Exception(error_msg))
    logger.debug({
        "event":"GET.REMOTE",
        "bucket_id":BUCKET_ID,
        "key":key
    })
    get_obj_response = obj_result_get_response.unwrap()
    obj_bytes        = get_obj_response.value
    obj              = CP.loads(obj_bytes)
    
    # f                = CP.loads(fbytes)
    print("FARGS", _msg.fargs)
    print("FKWARGS", _msg.fkwargs)
    res              = _msg.f(obj,*_msg.fargs, **_msg.fkwargs)
    # ___________________________________________________
    result_bytes = CP.dumps(res)
    
    logger.info({
        "event":"METHOD.EXEC.COMPLETED",
        "key":key,
        "fresult_size":len(result_bytes),
        "response_time": T.time()- start_time
    })

    result_metadata = J.dumps({}).encode(encoding="utf-8")
    
    await req_rep_socket.send_multipart([b"activex",b"METHOD.EXEC.COMPLETED",SUCCESS_STATUS,result_metadata, result_bytes])




async def main_req_rep():
    logger.debug("Server - Listen on {}://{}".format(protocol,uri2))
    while True:
        try:
            _start_time = T.time()
            multipart   = await req_rep_socket.recv_multipart()
            msg_result  = from_multipart_to_task(multipart=multipart)
            if msg_result.is_err:
                logger.error({
                    "msg":str(msg_result.unwrap_err())
                })
                await req_rep_socket.send_multipart([b"activex",b"REQUEST.FAILED",ERROR_STATUS,b"{}",b""])
                continue
            msg = msg_result.unwrap()

            topic       = msg.topic
            operation   = msg.operation
            metadata    = msg.metadata
            
            start_time = T.time()
            logger.debug("{} {}".format(topic,operation))
            if operation =="PUT.METADATA":
                _result = (await put_metadata(topic=topic, operation=operation,metadata=metadata))
                if _result.is_ok:
                    response = _result.unwrap()
                    await req_rep_socket.send_multipart([b"activex",b"PUT.METADATA.SUCCESSED",SUCCESS_STATUS,b"{}",response.encode()])
                    continue
                else:
                    await req_rep_socket.send_multipart([b"activex",b"PUT.METADATA.FAILED",ERROR_STATUS,b"{}",b""])


            elif operation =="METHOD.EXEC":
                # fbytes = msg.f
                result = await method_execution(msg)
                print(result)
                continue
            else:
                await req_rep_socket.send_multipart([b"activex",b"UKNOWN.OPERATION",ERROR_STATUS,b"{}",b""])
                continue
        except Exception as e:
            logger.error(str(e))
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])


async def main_sub():
    logger.debug("Subscriber - Listen on {}://{}".format(protocol,uri))
    while True: 
        try:
            msg = await pub_sub_socket.recv_multipart()
            print("msg",msg)
        except Exception as e:
            logger.error(e)


async def main():
    task1 = asyncio.create_task(main_req_rep())
    task2 = asyncio.create_task(main_sub())
    await asyncio.gather(task1,task2)

if __name__ == "__main__":
    asyncio.run(main=main())
    # loop = asyncio.get_event_loop()
    # tasks = [
        # loop.create_task(main_req_rep()),
        # loop.create_task(main()),
    # ]
    # loop.run_until_complete(asyncio.gather(*tasks))

    # main_req_rep()
    # main()