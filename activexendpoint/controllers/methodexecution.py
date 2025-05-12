import os
import zmq
import time as T
import json as J
import string
import types
import cloudpickle as CP

from option import Result,Ok,Err,Some,NONE
from typing import Any,Dict,List
from nanoid import generate as nanoid 

from axo import Axo
import activexendpoint.utils as U
from activexendpoint.interfaces import Heater,Task
from activexendpoint.utils import install_packages
from axo.endpoint.manager import DistributedEndpointManager
from activexendpoint.store import KVStore
# from activexendpoint.controllers import put_metadata
from activexendpoint.serde import Serde
import activexendpoint.constants as CONSTANTS
# 
from mictlanx.v4.asyncx import AsyncClient as MictlanXClient
# from mictlanx.v4.interfaces import GetBytesResponse,Metadata
import mictlanx.v4.interfaces as InterfaceX
import mictlanx.v4.models as ModelX
from mictlanx.logger.log import Log
# from activex.storage.data import StorageService
ALPHABET = string.ascii_lowercase+string.digits

AXO_ENDPOINT_IMAGE  = os.environ.get("AXO_ENDPOINT_IMAGE","nachocode/activex:endpoint")
AXO_ENDPOINT_ID     = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-0")
AXO_LOGGER_PATH     = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_LOGGER_WHEN     = os.environ.get("AXO_LOGGER_WHEN","h")
AXO_LOGGER_INTERVAL = int(os.environ.get("AXO_LOGGER_INTERVAL","24"))
AXO_SINK_PATH                 = os.environ.get("AXO_SINK_PATH","/sink")
AXO_SOURCE_PATH               = os.environ.get("AXO_SOURCE_PATH","/source")
AXO_DEBUG = bool(int(os.environ.get("AXO_DEBUG","1")))
logger = Log(
    console_handler_filter=lambda x: AXO_DEBUG,
    create_folder=True,
    error_log=True,
    name="activex.method_exeution",
    path=AXO_LOGGER_PATH,
    when=AXO_LOGGER_WHEN,
    interval=AXO_LOGGER_INTERVAL,
)
def __axo_method(f):
    def __inner(*args,**kwargs):
        print("ARGSSSSSSSS",args,kwargs)
        start = 1
        if len(args) == 1:
            start = 0
            
        return f(*args[start:],**kwargs)
    return __inner


async def __call(
        obj:Any,
        fname:str,
        ball:InterfaceX.Metadata,
        serde:Serde,
        sink_bucket_id:str,
        axo_sink_path_sink_bucket_id_path:str,
        storage_service:MictlanXClient,
        task_fkwargs:Dict[str,Any] = {},
        task_fargs:List[Any] = ()
):
    axo_sink_key  = nanoid(alphabet=string.ascii_lowercase+string.digits,size=16)
    axo_sink_path = "{}/{}".format(axo_sink_path_sink_bucket_id_path,axo_sink_key)
    axo_result_id = "{}.{}.{}".format(fname,sink_bucket_id ,axo_sink_key )
    fkwargs = {
        **task_fkwargs,
        "axo_result_id":axo_result_id,
        "axo_sink_path_sink_bucket_id_path":axo_sink_path_sink_bucket_id_path,
        "axo_sink_path":axo_sink_path,
        "axo_sink_key":axo_sink_key,
        "source_bucket_id":ball.bucket_id,
        "source_key":ball.key,
        "method_name":fname,
        "metadata":ball.tags,
        "storage":storage_service
    }
    t_call_start = T.time()
    # method_call_result = Axo.call(*task.fargs,instance=obj,**fkwargs)
    method_call_result = Axo.call(*task_fargs,**{"instance":obj,**fkwargs})
    if method_call_result.is_ok:
        logger.info({
            "event":"METHOD.CALL",
            "method_name":fname,
            "axo_result_id":axo_result_id,
            "axo_sink_path":axo_sink_path,
            "axo_sink_key":axo_sink_key,
            "source_bucket_id":ball.bucket_id,
            "source_key":ball.key,
            "response_time":T.time() -  t_call_start
        })
        method_call_response = method_call_result.unwrap()
        if isinstance(method_call_response, Exception):
            logger.error({
                "event":"METHOD.CALL.FAILED",
                "msg":str(method_call_response)
            })
            return Err(method_call_response)
            
        # print("METHOD_CALL.RESPONSE", method_call_result)
        if not method_call_response == None:
            (f_serialize_mode,f_result_bytes)= serde.serialize_fresult(result=method_call_response).unwrap()
            axo_fsink_key = nanoid(alphabet=string.ascii_lowercase+string.digits, size=16)
            # result_json[axo_result_id] = f_result_bytes.decode() if f_serialize_mode == 0 else axo_fsink_key
            put_result   = storage_service.put_chunked(
                chunks=U.byte_generator(f_result_bytes),
                bucket_id=sink_bucket_id,
                key=axo_fsink_key,
                tags={
                    "method_name":fname,
                    "axo_result_id":axo_result_id,
                    "axo_sink_path":axo_sink_path,
                    "axo_sink_key":axo_sink_key,
                    "source_bucket_id":ball.bucket_id,
                    "source_key":ball.key,
                }
            )
            if put_result.is_err:
                return Err(put_result.unwrap_err())
                # fbs = result_json.setdefault("failed_balls",0)
                # result_json["failed_balls"] = fbs +1
                # logger.error({
                #     "event":"PUT.CHUNKED.FAILED",
                #     "bucket_id":axo_bucket_id,
                #     "key":axo_fsink_key,
                # })
            else:
                status = 1 
                return Ok(method_call_response)
                # fbs = result_json.setdefault("successed_balls",0)
                # result_json["successed_balls"] = fbs +1
        else:
            return Ok(None)
            # return Err(Exception("{} execution failed".format(fname)))
            # logger.warning({
            #     "event":"METHOD.EXEC.NO.OUTPUT",
            #     "axo_source_bucket_id":source_bucket_id,
            #     # "axo_source_path":source_ball_local_path,
            #     "axo_sink_bucket_id":sink_bucket_id,
            #     "axo_bucket_sink_path":axo_sink_path_source_bucket_id_path,
            #     "axo_sink_path":axo_sink_path,
            #     "axo_sink_key":axo_sink_key,
            #     "response_time": T.time()- start_time
            # })
            
            # raise 
    else:
        error = method_call_result.unwrap_err()
        logger.error({
            "event":"METHOD.EXCUTION.FAILED",
            "reason":str(error )
        })
        return Err(error)


async def __method_execution(
        serde:Serde,
        storage_service:MictlanXClient,
        store:KVStore,
        req_rep_socket:zmq.Socket,
        task:Task)->Result[Any, Exception]:
    start_time       = T.time()
    axo_key          = task.get_axo_key()
    axo_bucket_id    = task.get_axo_bucket_id()
    source_bucket_id = task.get_source_bucket_id()
    sink_bucket_id   = task.get_sink_bucket_id()
    axo_sink_path_source_bucket_id_path = "{}/{}".format(AXO_SINK_PATH,source_bucket_id)
    axo_sink_path_sink_bucket_id_path   = "{}/{}".format(AXO_SINK_PATH,sink_bucket_id)
    os.makedirs(axo_sink_path_sink_bucket_id_path,exist_ok=True)
    logger.debug({
        "axo_key":axo_key,
        "axo_bucket_id":axo_bucket_id,
        "axo_source_bucket_id":source_bucket_id,
        "axo_sink_bucket_id":sink_bucket_id
    })
    try:
        # axo_key validation _______________________________________________________________________________________
        if axo_key == -1:
            error_msg = "Key not found in metadata"
            logger.error({
                "msg":error_msg,
                "operation":"METHOD.EXEC"
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
        # _______________________________________________________________________________________

        # _______________________________________________________________________________________
        maybe_mictlanx_metadata = store.get(key=axo_key)
        if maybe_mictlanx_metadata.is_none:
            logger.warning({
                "event":"LOCAL.NOT.FOUND",
                "axo_bucket_id":axo_bucket_id,
                "key":axo_key,
            })
            get_metadata_start_time = T.time()
            get_metadata_result:Result[ModelX.Ball,Exception] = await storage_service.get_metadata(
                bucket_id     = axo_bucket_id,
                ball_id       = f"{axo_key}_source_code",
            )
            
            # Check if get_metadata got an error_____________________________________________
            if get_metadata_result.is_err:
                error_msg = "{} not found".format(axo_key)
                logger.error({
                    "event":"GET.METADATA.FAILED",
                    "error":error_msg,
                    "axo_bucket_id":axo_bucket_id,
                    "key":axo_key
                })
                await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",b""])
                return Err(Exception(error_msg))
            # _______________________________________________________________________________________

            remote_metadata = get_metadata_result.unwrap()
            logger.info({
                "event":"GET.REMOTE.METADATA",
                "bucket_id":axo_bucket_id,
                "key":axo_key,
                "response_time":T.time() - get_metadata_start_time
            })
            # remote_metadata.tags
            # await put_metadata()
            local_tags = remote_metadata.chunks[0].tags
            store.put(key=axo_key, value=local_tags )
            maybe_mictlanx_metadata = Some(local_tags)
        
        local_metadata = maybe_mictlanx_metadata.unwrap()
        module         = local_metadata.get("axo_module",-1)
        name           = local_metadata.get("axo_name",-1)
        # add_dummy_module(module, name, Dummy)
        # _______________________________________________________________________________________
        if module == -1 or name == -1:
            error_msg = "module or name attribute not found in tags"
            logger.error({
                "event":"MODULE.OR.NAME.NOT.FOUND",
                "msg":error_msg,
                "bucket_id":axo_bucket_id,
                "key":axo_key,
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
        # _______________________________________________________________________________________
        mictlanx_get_start_time =  T.time()

        attrs_result_get_response = await storage_service.get(bucket_id=axo_bucket_id, key=f"{axo_key}_attrs")

        obj_result_get_response = await storage_service.get(
            bucket_id=axo_bucket_id,
            key=f"{axo_key}_source_code"
        )
        if obj_result_get_response.is_err:
            error_msg = "Get source code failed"
            logger.error({
                "msg":error_msg, 
                "bucket_id":axo_bucket_id,
                "key":axo_key
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",error_msg.encode()])
            return Err(Exception(error_msg))
        if attrs_result_get_response.is_err:
            error_msg = "Get attributes failed"
            logger.error({
                "msg":error_msg, 
                "bucket_id":axo_bucket_id,
                "key":axo_key
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",error_msg.encode()])
            return Err(Exception(error_msg))

        # _______________________________________________________________________________________
        get_obj_response = obj_result_get_response.unwrap()
        source_code = CP.loads(get_obj_response.data.tobytes())
        attrs_response = attrs_result_get_response.unwrap()
        attrs = CP.loads(attrs_response.data.tobytes())
        mod                        = types.ModuleType("__axo_dynamic__")
        mod.__dict__["Axo"]        = Axo
        mod.__dict__["axo_method"] = __axo_method
        class_name = get_obj_response.metadatas[0].tags.get("axo_class_name")
        exec(source_code, mod.__dict__)
        X = getattr(mod,class_name)
        obj = X(**attrs)
        # GET SOURCE BUCKET
        # _______________________________________________________________________________________
        bucket_result = await storage_service.get_bucket_metadata(bucket_id=source_bucket_id)
        print("BIUCKET_REUSLT",bucket_result)
        if bucket_result.is_err:
            error_msg = "Get bucket failed"
            logger.error({
                "msg":error_msg, 
                "bucket_id":axo_bucket_id,
                "key":axo_key
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",error_msg.encode()])
            return Err(Exception(error_msg))        

        bucket = bucket_result.unwrap()
        for k,b in bucket.balls.items():
            print(b.checksum,axo_sink_path_sink_bucket_id_path)


        f = getattr(obj, task.metadata.get("fname"))
        for attr_name, attr_value in attrs.items():
            setattr(obj, attr_name, attr_value) 
        print(task.fargs,task.fkwargs)
        result = f(*task.fargs)

        print("RESULT", result)
        await req_rep_socket.send_multipart([b"activex",b"METHOD.EXEC.COMPLETED",CONSTANTS.SUCCESS_STATUS,b"{}", f"{result}".encode() ])
        # print(f(**attrs))
        # print(getattr(obj, task))


        # await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",b""])
        # return Err(Exception("BOOM!"))

        # Pattern
        # Get bucket


        # bucket_metadata_gen = storage_service.get_all_bucket_metadata(bucket_id=source_bucket_id)
        # result_json = {
        #     "successed_balls":0,
        #     "failed_balls":0,
        #     "response_time":0
        # }
        # # for source_ball_local_path in source_bucket_files:
        # fname = task.metadata.get("fname",task.f.__name__)
        # skip_balls = []
        # for router_response in bucket_metadata_gen:
        #     for ball in router_response.balls:
        #         status = -1
        #         combined_key = "{}@{}".format(ball.bucket_id, ball.key)
        #         if combined_key in skip_balls:
        #             logger.debug({
        #                 "event":"SKIP.BALL",
        #                 "bucket_id":ball.bucket_id,
        #                 "key":ball.key,
        #                 "status":status
        #             })
        #             continue
        #         axo_sink_key  = nanoid(alphabet=string.ascii_lowercase+string.digits,size=16)
        #         axo_sink_path = "{}/{}".format(axo_sink_path_sink_bucket_id_path,axo_sink_key)
        #         axo_result_id = "{}.{}.{}".format(fname,sink_bucket_id ,axo_sink_key )
        #         fkwargs = {
        #             **task.fkwargs,
        #             "axo_result_id":axo_result_id,
        #             "axo_sink_path_sink_bucket_id_path":axo_sink_path_sink_bucket_id_path,
        #             "axo_sink_path":axo_sink_path,
        #             "axo_sink_key":axo_sink_key,
        #             "source_bucket_id":ball.bucket_id,
        #             "source_key":ball.key,
        #             "method_name":fname,
        #             "metadata":ball.tags,
        #             "storage":storage_service
        #         }
        #         t_call_start = T.time()
        #         # method_call_result = Axo.call(*task.fargs,instance=obj,**fkwargs)
        #         method_call_result = Axo.call(*task.fargs,**{"instance":axo_obj,**fkwargs})
        #         if method_call_result.is_ok:
        #             logger.info({
        #                 "event":"METHOD.CALL",
        #                 "method_name":fname,
        #                 "axo_result_id":axo_result_id,
        #                 "axo_sink_path":axo_sink_path,
        #                 "axo_sink_key":axo_sink_key,
        #                 "source_bucket_id":ball.bucket_id,
        #                 "source_key":ball.key,
        #                 "response_time":T.time() -  t_call_start
        #             })
        #             method_call_result = method_call_result.unwrap()
        #             if isinstance(method_call_result, Exception):
        #                 logger.error({
        #                     "event":"METHOD.CALL.FAILED",
        #                     "msg":str(method_call_result)
        #                 })
        #                 continue
        #             if not method_call_result == None:
        #                 (f_serialize_mode,f_result_bytes)= serde.serialize_fresult(result=method_call_result).unwrap()
        #                 axo_fsink_key = nanoid(alphabet=string.ascii_lowercase+string.digits, size=16)
        #                 result_json[axo_result_id] = f_result_bytes.decode() if f_serialize_mode == 0 else axo_fsink_key
        #                 put_result   = storage_service.put_chunked(
        #                     chunks=U.byte_generator(f_result_bytes),
        #                     bucket_id=sink_bucket_id,
        #                     key=axo_fsink_key,
        #                     tags={
        #                         "method_name":fname,
        #                         "axo_result_id":axo_result_id,
        #                         "axo_sink_path":axo_sink_path,
        #                         "axo_sink_key":axo_sink_key,
        #                         "source_bucket_id":ball.bucket_id,
        #                         "source_key":ball.key,
        #                     }
        #                 )
        #                 if put_result.is_err:
        #                     fbs = result_json.setdefault("failed_balls",0)
        #                     result_json["failed_balls"] = fbs +1
        #                     logger.error({
        #                         "event":"PUT.CHUNKED.FAILED",
        #                         "bucket_id":axo_bucket_id,
        #                         "key":axo_fsink_key,
        #                     })
        #                 else:
        #                     status = 1 
        #                     fbs = result_json.setdefault("successed_balls",0)
        #                     result_json["successed_balls"] = fbs +1
        #             else:
        #                 logger.warning({
        #                     "event":"METHOD.EXEC.NO.OUTPUT",
        #                     "axo_source_bucket_id":source_bucket_id,
        #                     # "axo_source_path":source_ball_local_path,
        #                     "axo_sink_bucket_id":sink_bucket_id,
        #                     "axo_bucket_sink_path":axo_sink_path_source_bucket_id_path,
        #                     "axo_sink_path":axo_sink_path,
        #                     "axo_sink_key":axo_sink_key,
        #                     "response_time": T.time()- start_time
        #                 })
                        
        #                 # raise Exception("{} execution failed".format(fname))
        #         else:
        #             logger.error({
        #                 "event":"METHOD.EXCUTION.FAILED",
        #                 "reason":str(method_call_result.unwrap_err())
        #             })
                

        #         if status == 0:
        #             skip_balls.append(combined_key)

        #             # continue

        # if result_json["failed_balls"] ==0 and result_json["successed_balls"] == 0 :
        #     method_result = await __call(
        #         obj = axo_obj,
        #         axo_sink_path_sink_bucket_id_path=axo_sink_path_sink_bucket_id_path,
        #         ball=InterfaceX.Metadata(tags={},ball_id="",bucket_id="",checksum="",content_type="",is_disabled=False,key="",producer_id="",size=0),
        #         fname=fname,
        #         serde=serde,
        #         sink_bucket_id=sink_bucket_id,
        #         storage_service=storage_service,
        #         task_fargs=task.fargs,
        #         task_fkwargs=task.fkwargs,
        #     )


        # logger.info({
        #     "event":"METHOD.EXEC.COMPLETED",
        #     "method_name":fname,
        #     "axo_source_bucket_id":source_bucket_id,
        #     "axo_sink_bucket_id":sink_bucket_id,
        #     "response_time": T.time()- start_time
        # })
        # result_json["response_time"] = T.time()- start_time
        # result_metadata = J.dumps({}).encode(encoding="utf-8")
        # result_bytes = J.dumps(result_json).encode()
        # await req_rep_socket.send_multipart([b"activex",b"METHOD.EXEC.COMPLETED",CONSTANTS.SUCCESS_STATUS,result_metadata, result_bytes])
    except Exception as e:
        error_msg = "Uknown error"
        logger.error({
            "event":"METHDO.EXECUTION.FAILED",
            "msg":error_msg,
            "raw_error":str(e)
        })
        await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",b""])
        return Err(Exception(error_msg))





async def method_exeution(
        endpoint_manager:DistributedEndpointManager,
        heater:Heater,
        serde:Serde,
        storage_service:MictlanXClient,
        store:KVStore,
        req_rep_socket:zmq.Socket,
        task:Task
):
    heater.warm(task_id=task.task_id)
    dependencies = task.get_dependencies()
    logger.debug({
        "event":"DEPENDENCIES.SHOW",
        "dependencies":dependencies
    })
    install_packages(packages=dependencies)

    endpoint_id = task.get_endpoint_id()
    exists      = endpoint_manager.exists(endpoint_id=endpoint_id)

    logger.debug({
        "event":"ENDPOINT.MANAGER",
        "endpoints":str(endpoint_manager.endpoints),
        "endpoint_id":AXO_ENDPOINT_ID,
        "current_endpoint_id":endpoint_id,
        "size":len(endpoint_manager.endpoints),
        "exists":exists
    })
    result = await __method_execution(
        serde           = serde,
        storage_service = storage_service,
        store           = store,
        req_rep_socket  = req_rep_socket,
        task            = task,
    )