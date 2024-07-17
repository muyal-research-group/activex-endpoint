import os
import zmq
import time as T
import json as J
import string
from option import Result,Ok,Err,Some,NONE
from typing import Any
from nanoid import generate as nanoid 

from activex import ActiveX
import activexendpoint.utils as U
from activexendpoint.interfaces import Heater,Task
from activexendpoint.utils import install_packages
from activex.endpoint import XoloEndpointManager
from activexendpoint.store import KVStore
from activexendpoint.controllers import put_metadata
from activexendpoint.serde import Serde
import activexendpoint.constants as CONSTANTS
from mictlanx.v4.interfaces import GetMetadataResponse,GetBytesResponse
from mictlanx.logger.log import Log
from activex.storage.data import StorageService
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
async def __method_execution(
        serde:Serde,
        storage_service:StorageService,
        store:KVStore,
        req_rep_socket:zmq.Socket,
        task:Task)->Result[Any, Exception]:
    start_time       = T.time()
    axo_key          = task.get_axo_key()
    axo_bucket_id    = task.get_axo_bucket_id()
    source_bucket_id = task.get_source_bucket_id()
    sink_bucket_id   = task.get_sink_bucket_id()

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
            get_metadata_result:Result[GetMetadataResponse, Exception]= storage_service.get_metadata(
                key       = axo_key,
                bucket_id = axo_bucket_id
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
            await put_metadata(metadata=remote_metadata.metadata.tags)
            maybe_mictlanx_metadata = Some(remote_metadata.metadata.tags)
        
        local_metadata = maybe_mictlanx_metadata.unwrap()
        module         = local_metadata.get("module",-1)
        name           = local_metadata.get("name",-1)
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

        obj_result_get_response :Result[GetBytesResponse,Exception]= storage_service.get_with_retry(
            bucket_id=axo_bucket_id,
            key=axo_key
        )

        
        # _______________________________________________________________________________________
        if obj_result_get_response.is_err:
            error_msg = "get_to_file failed"
            logger.error({
                "msg":error_msg, 
                "bucket_id":axo_bucket_id,
                "key":axo_key
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
        # _______________________________________________________________________________________
        get_obj_response = obj_result_get_response.unwrap()
        obj_bytes        = get_obj_response.value
        logger.info({
            "event":"GET.OBJECT.REMOTE",
            "bucket_id":axo_bucket_id,
            "key":axo_key,
            "storage_service":"mictlanx",
            "response_time":T.time() - mictlanx_get_start_time
        })
        # _______________________________________________________________________________________
        des_start_time = T.time()
        obj_resul              =serde.deserialize(obj_bytes)
        if obj_resul.is_err:
            error_msg = "DESERIALIZED.FAILED"
            logger.error({
                "event":error_msg,
                "bucket_id":axo_bucket_id,
                "key":axo_key,
                "msg":str(obj_resul.unwrap_err())
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
        # _______________________________________________________________________________________

        obj = obj_resul.unwrap()
        logger.info({
            "event":"DESERALIZATION",
            "bucket_id":axo_bucket_id,
            "key":axo_key,
            "response_time":T.time() - des_start_time
        })
        # ____________________________________________________
        logger.debug({
            "event":"GET.SOURCE.DATA",
            "axo_source_bucket_id":source_bucket_id,
        })
        # Pattern
        # Get bucket
        axo_sink_path_source_bucket_id_path = "{}/{}".format(AXO_SINK_PATH,source_bucket_id)
        axo_sink_path_sink_bucket_id_path   = "{}/{}".format(AXO_SINK_PATH,sink_bucket_id)
        os.makedirs(axo_sink_path_sink_bucket_id_path,exist_ok=True)

        bucket_metadata_gen = storage_service.get_all_bucket_metadata(bucket_id=source_bucket_id)
        result_json = {
            "successed_balls":0,
            "failed_balls":0,
            "response_time":0
        }
        # for source_ball_local_path in source_bucket_files:
        fname = task.metadata.get("fname",task.f.__name__)
        skip_balls = []
        for router_response in bucket_metadata_gen:
            for ball in router_response.balls:
                status = -1
                combined_key = "{}@{}".format(ball.bucket_id, ball.key)
                if combined_key in skip_balls:
                    logger.debug({
                        "event":"SKIP.BALL",
                        "bucket_id":ball.bucket_id,
                        "key":ball.key,
                        "status":status
                    })
                    continue
                axo_sink_key  = nanoid(alphabet=string.ascii_lowercase+string.digits,size=16)
                axo_sink_path = "{}/{}".format(axo_sink_path_sink_bucket_id_path,axo_sink_key)
                axo_result_id = "{}.{}.{}".format(fname,sink_bucket_id ,axo_sink_key )
                fkwargs = {
                    **task.fkwargs,
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
                method_call_result = ActiveX.call(*task.fargs,instance=obj,**fkwargs)
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
                    method_call_result = method_call_result.unwrap()
                    if isinstance(method_call_result, Exception):
                        logger.error({
                            "event":"METHOD.CALL.FAILED",
                            "msg":str(method_call_result)
                        })
                        continue
                    print("METHOD_CALL.RESPONSE", method_call_result)
                    if not method_call_result == None:
                        (f_serialize_mode,f_result_bytes)= serde.serialize_fresult(result=method_call_result).unwrap()
                        axo_fsink_key = nanoid(alphabet=string.ascii_lowercase+string.digits, size=16)
                        result_json[axo_result_id] = f_result_bytes.decode() if f_serialize_mode == 0 else axo_fsink_key
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
                            fbs = result_json.setdefault("failed_balls",0)
                            result_json["failed_balls"] = fbs +1
                            logger.error({
                                "event":"PUT.CHUNKED.FAILED",
                                "bucket_id":axo_bucket_id,
                                "key":axo_fsink_key,
                            })
                        else:
                            status = 1 
                            fbs = result_json.setdefault("successed_balls",0)
                            result_json["successed_balls"] = fbs +1
                    else:
                        logger.warning({
                            "event":"METHOD.EXEC.NO.OUTPUT",
                            "axo_source_bucket_id":source_bucket_id,
                            # "axo_source_path":source_ball_local_path,
                            "axo_sink_bucket_id":sink_bucket_id,
                            "axo_bucket_sink_path":axo_sink_path_source_bucket_id_path,
                            "axo_sink_path":axo_sink_path,
                            "axo_sink_key":axo_sink_key,
                            "response_time": T.time()- start_time
                        })
                        
                        # raise Exception("{} execution failed".format(fname))
                else:
                    logger.error({
                        "event":"METHOD.EXCUTION.FAILED",
                        "reason":str(method_call_result.unwrap_err())
                    })
                

                if status == 0:
                    skip_balls.append(combined_key)

                    # continue

        logger.info({
            "event":"METHOD.EXEC.COMPLETED",
            "method_name":fname,
            "axo_source_bucket_id":source_bucket_id,
            # "axo_source_path":source_ball_local_path,
            "axo_sink_bucket_id":sink_bucket_id,
            # "axo_bucket_sink_path":axo_sink_path_source_bucket_id_path,
            # "axo_sink_path":axo_sink_path,
            # "axo_sink_key":axo_sink_key,
            "response_time": T.time()- start_time
        })
        result_json["response_time"] = T.time()- start_time
        result_metadata = J.dumps({}).encode(encoding="utf-8")
        result_bytes = J.dumps(result_json).encode()
        await req_rep_socket.send_multipart([b"activex",b"METHOD.EXEC.COMPLETED",CONSTANTS.SUCCESS_STATUS,result_metadata, result_bytes])
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
        endpoint_manager:XoloEndpointManager,
        heater:Heater,
        serde:Serde,
        storage_service:StorageService,
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