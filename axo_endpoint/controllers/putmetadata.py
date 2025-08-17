import json as J
import string
from typing import Dict,Any,List
import time as T
import asyncio
import os
# 
from option import Err,Result,Ok,Option,Some,NONE
import zmq.asyncio 
# 
from axo_endpoint.interfaces import Heater,Task
from axo.endpoint.manager import DistributedEndpointManager
from axo.endpoint.endpoint import DistributedEndpoint
import axo_endpoint.utils as U
import axo_endpoint.constants  as CONSTANTS
from axo_endpoint.store import KVStore
from axo.core.models import MetadataX

from mictlanx.v4.summoner.summoner import Summoner
from axo.log import get_logger
from typing import Dict, Any, Optional, Tuple
from axo.errors import AxoError
from axo.enums import AxoErrorType
# from axoen
# from mictlanx.logger.log import Log

ALPHABET = string.ascii_lowercase+string.digits
AXO_ENDPOINT_IMAGE  = os.environ.get("AXO_ENDPOINT_IMAGE","nachocode/activex:endpoint")
AXO_ENDPOINT_ID     = os.environ.get("AXO_ENDPOINT_ID","axo-endpoint-0")
AXO_LOGGER_PATH     = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_DEBUG = bool(int(os.environ.get("AXO_DEBUG","1")))
logger = get_logger(name=__name__, ltype="JSON",path=AXO_LOGGER_PATH)
# logger = Log(
#     console_handler_filter=lambda x: AXO_DEBUG,
#     create_folder=True,
#     error_log=True,
#     name="activex.put.metadata",
#     path=AXO_LOGGER_PATH,
#     when=AXO_LOGGER_WHEN,
#     interval=AXO_LOGGER_INTERVAL,
# )


async def __put_metadata(socket:zmq.Socket,store:KVStore,metadata:Dict[str,Any])->Result[str, AxoError]:
    start_time = T.time()
    axo_key        = metadata.get("axo_key", -1)
    print("__METADATA",axo_key)
    if axo_key == -1:
        e = AxoError.make(error_type=AxoErrorType.BAD_REQUEST, msg="Malformed request: It does not contain id field.")
        await U.send_error_axo(socket=socket,error=e,operation="PUT_METADATA",task_id = metadata.get("task_id",""))
        # await req_rep_socket.send_multipart([b"activex",b"BAD.REQUEST", J.dumps(error_obj).encode() ])
        # logger.error("{} {}".format("BAD.REQUEST",axo_key))
        return Err(e)
        # return Err(Exception(error_obj.get("detail","Uknown error")))
        # continue
    if store.exists(key=axo_key):
        e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR,msg="{} already exists".format(axo_key))
        await U.send_error_axo(socket=socket, operation="PUT_METADATA",task_id=metadata.get("task_id",""),error=e)
        return Err(e)
        # error_obj = {"key":axo_key, "detail":}
        # await socket.send_multipart([b"activex",b"ALREADY.EXISTS", J.dumps(error_obj).encode() ])
        # logger.error("{} {}".format("ALREADY.EXISTS",axo_key))
        # return Err(Exception(error_obj.get("detail","Uknown error")))
    
    store.put(key=axo_key, value= metadata)
    rt = T.time() - start_time
    logger.info({
        "event":"PUT.METADATA",
        "key":axo_key,
        **metadata,
        "response_time":rt
    })
        # "{} {} {}".format("PUT.METADATA",key,rt))
    return Ok(axo_key)


async def __deploy_endpoint(summoner:Summoner,endpoint_id:str, req_res_port:int, pubsub_port:int,dependencies:List[str]=[]):
    try:
        deploy_endpoint_start_time = T.time()

        # pubsub_port = endpoint_manager.get_available_pubsub_port()
        # req_res_port= endpoint_manager.get_available_req_res_port()
        logger.debug({
            "event":"DEPLOY.ENDPOINT",
            "endpoint_id":endpoint_id,
            "pubsub_port":pubsub_port,
            "req_res_port":req_res_port
        })
        endpoint_deploy_result = U.deploy_endpoint(
            summoner=summoner,
            endpoint_id=endpoint_id,
            pubsub_port=pubsub_port,
            req_res_port=req_res_port,
            dependencies=dependencies,
            image=AXO_ENDPOINT_IMAGE

        )
        if endpoint_deploy_result.is_ok:
            container_endpoint = endpoint_deploy_result.unwrap()
            # endpoint_manager.add_endpoint(
            #     endpoint_id  = endpoint_id,
            #     hostname     = container_endpoint.ip_addr,
            #     req_res_port = req_res_port,
            #     pubsub_port  = pubsub_port
            # )
            logger.info({
                "event":"DEPLOY.ENDPOINT",
                "endpoint_id":endpoint_id,
                "response_time":T.time() - deploy_endpoint_start_time
            })
            return Ok(DistributedEndpoint(endpoint_id=endpoint_id, hostname=container_endpoint.ip_addr, req_res_port=req_res_port,pubsub_port=pubsub_port))
        
        else:
            e = endpoint_deploy_result.unwrap_err()
            logger.error({
                "error":"DEPLOY.ENDPOINT.FAILED",
                "msg":str(e),
                "endpoint_id":endpoint_id,
                "req_res_port":req_res_port,
                "pubsub_port":pubsub_port
            })
            return Err(e)
    except Exception as e:
        return Err(e)





# Assumptions: these exist in your codebase
# from axo.result import Ok, Err, Result
# from axo.types import KVStore, MetadataX, Task, DistributedEndpointManager, Summoner, Heater
# from axo.constants import AXO_ENDPOINT_ID, CONSTANTS
# from axo.logger import logger
# import zmq

METADATA_OP_TIMEOUT: int = 30  # seconds (tune as needed)

def _extract_endpoint_id(task: Task, metadata: Dict[str, Any]) -> str:
    # Priority: explicit in metadata -> task default -> local constant
    # return metadata.get("endpoint_id") or task.get_endpoint_id() or AXO_ENDPOINT_ID
    return task.get_endpoint_id() or AXO_ENDPOINT_ID

def _validate_metadata(metadata: Dict[str, Any]) -> Result[Optional[str], AxoError]:
    """
    Validates minimal metadata requirements.
    Returns (key, error_message). If error_message is not None, validation failed.
    """
    key = metadata.get("axo_key")
    if not key or not isinstance(key, str):
         return Err(AxoError.make(AxoErrorType.BAD_REQUEST,msg="Missing or invalidad 'axo_key' in metadata"))
    # elif key != task.task_id:
        # return Err(AxoError.make(error_type=AxoErrorType.BAD_REQUEST, msg=""))
        # return None, "Missing or invalid 'id' in metadata."
    return Ok(key)

async def _ensure_endpoint(endpoint_manager: "DistributedEndpointManager",
                           summoner: "Summoner",
                           endpoint_id: str) -> Result[Option[DistributedEndpoint],AxoError]:
    """
    Ensure the target endpoint exists. Deploys it if missing.
    """
    try: 
        t1 = T.time()
        exists = endpoint_manager.exists(endpoint_id=endpoint_id)
        logger.debug({
            "event": "ENDPOINT.CHECK",
            "endpoint_id": endpoint_id,
            "exists": exists,
            "known_endpoints": list(endpoint_manager.endpoints.keys()),
            "size": len(endpoint_manager.endpoints),
            "current_endpoint_id": AXO_ENDPOINT_ID,
        })
        if exists:
            return Ok(NONE)

        # Allocate ports *before* deploy to avoid races
        req_res_port = endpoint_manager.get_available_req_res_port()
        pubsub_port  = endpoint_manager.get_available_pubsub_port()

        logger.info({
            "event": "ENDPOINT.DEPLOY.START",
            "endpoint_id": endpoint_id,
            "req_res_port": req_res_port,
            "pubsub_port": pubsub_port,
        })

        # __deploy_endpoint async in your codebase; keep it awaited if it returns a coroutine
        deploy_result = await __deploy_endpoint(
            summoner     = summoner,
            endpoint_id  = endpoint_id,
            req_res_port = req_res_port,
            pubsub_port  = pubsub_port,
        )
        # deploy_result = await maybe_coro

        if deploy_result.is_err:
            e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR,msg= f"Failed to deploy endpoint '{endpoint_id}': {deploy_result.unwrap_err()}")
            return Err(e)
            # raise RuntimeError()

        logger.info({
            "event": "ENDPOINT.DEPLOY.DONE",
            "endpoint_id": endpoint_id,
            "response_time":T.time() - t1
        })
        return Ok(Some(deploy_result.unwrap()))
    except Exception as e:
        return Err(AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR,msg=str(e)))

async def put_metadata(
    store: "KVStore",
    socket: "zmq.Socket",
    h: "Heater",
    endpoint_manager: "DistributedEndpointManager",
    summoner: "Summoner",
    task: "Task",
)->Result[str,AxoError]:
    """
    Put metadata into an Axo Endpoint.

    Behavior:
      1) Prepares runtime (heater warm + on-demand dependency install).
      2) Determines the target endpoint (metadata.endpoint_id -> task -> local).
      3) Ensures the endpoint is deployed (auto-deploy if missing).
      4) If the target is remote, sends a PUT to that endpoint.
         If it's the local endpoint, writes via __put_metadata().
      5) Responds over ZMQ with a structured multipart message.

    Contracts:
      - Expects `task.metadata` with at least an `"id"` field (the key).
      - Uses Result[Ok|Err] semantics: returns Ok(()) on success, Err(str/Exception) on failure.
      - Enforces a timeout on the actual put operation.

    Wire responses:
      [b"activex", b"PUT.METADATA.SUCCESSED|FAILED", STATUS_CODE, b"{}", key_bytes]
    """
    _start_time = T.time()

    try:
        metadata: Dict[str, Any] = task.metadata or {}
        h.warm(task_id=task.task_id)  # keep existing behavior (appears sync)

        # (Optional) resolve and install dependencies
        try:
            dependencies = task.get_dependencies()
            if dependencies:
                U.install_packages(packages=dependencies)
                logger.debug({
                    "event": "DEPENDENCIES.INSTALLED",
                    "count": len(dependencies),
                    "deps": dependencies,
                    "service_time":T.time()-_start_time
                })
        except Exception as dep_err:
            # Don't hard-fail if dep install is best-effort; choose policy here.
            logger.warning({
                "event": "DEPENDENCIES.INSTALL.FAILED",
                "error": str(dep_err),
                "service_time":T.time()-_start_time
            })

        # Validate metadata & resolve endpoint
        key_result = _validate_metadata(metadata)
        if key_result.is_err:
            # error = AxoError.make(error_type=AxoErrorType.BAD_REQUEST,msg =f"Put operation failed: {key_result.unwrap_err()}" )
            # await U.send_error_axo(
            #     socket=socket,
            #     operation=task.operation,
            #     task_id=task.task_id,
            #     error=error
            #     # msg_id=
            # )
            return Err(key_result.unwrap_err())
            # await req_rep_socket.send_multipart([b"activex", b"PUT.METADATA.FAILED",
                                                #  CONSTANTS.ERROR_STATUS, b"{}", b""])
            # return Err(err_msg)
        key = key_result.unwrap()

        endpoint_id: str = _extract_endpoint_id(task, metadata)

        # Ensure endpoint exists (auto-deploy if needed)
        endpoint_result_maybe = await _ensure_endpoint(endpoint_manager, summoner, endpoint_id)
        # print("ENDPOINT_RESLT_MAYHBEW", endpoint_result_maybe)
        if endpoint_result_maybe.is_err:
            return Err(endpoint_result_maybe.unwrap_err())
        


        # Remote vs local path
        if endpoint_id != AXO_ENDPOINT_ID:
            endpointx = endpoint_manager.get_endpoint(endpoint_id=endpoint_id)
            if endpointx is None:
                e_msg = f"Endpoint '{endpoint_id}' not found after deployment."
                e     = AxoError.make(error_type=AxoErrorType.NOT_FOUND, msg=e_msg)
                return Err(e)

            # Build MetadataX up-front to validate schema early
            try:
                meta_obj = MetadataX(**metadata)
            except Exception as mx_err:
                msg = f"Invalid metadata schema: {mx_err}"
                e   = AxoError.make(error_type=AxoErrorType.BAD_REQUEST, msg=msg)
                return Err(e)

            # Put with timeout
            try:
                put_res = await asyncio.wait_for(
                    endpointx.put(key=key, metadata=meta_obj),
                    timeout=METADATA_OP_TIMEOUT
                )
            except asyncio.TimeoutError:
                msg = f"Timeout putting metadata to endpoint '{endpoint_id}'."
                e = AxoError.make(error_type=AxoErrorType.TIMEOUT, msg = msg)
                return Err(e)

            if put_res.is_ok:
                logger.info({
                    "event": "PUT.METADATA.COMPLETED",
                    "target": "remote",
                    "endpoint_id": endpoint_id,
                    "key": key,
                    "response_time": T.time() - _start_time
                })
                # await socket.send_multipart([b"activex", b"PUT.METADATA.SUCCESSED",
                                                    #  CONSTANTS.SUCCESS_STATUS, b"{}", key.encode()])
                return Ok(key)
            else:
                e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR, msg =str(put_res.unwrap_err()) )
                return Err(e)
        # Local path
        try:
            _result = await asyncio.wait_for(
                __put_metadata(socket=socket, store=store, metadata=metadata),
                timeout=METADATA_OP_TIMEOUT
            )
        except asyncio.TimeoutError:
            msg = "Timeout putting metadata on local endpoint."
            e = AxoError.make(error_type=AxoErrorType.TIMEOUT, msg = msg)
            return Err(msg)
        

        if _result.is_ok:
            response_key = _result.unwrap()
            logger.info({
                "event": "PUT.METADATA.COMPLETED",
                "target": "local",
                "key": key,
                "response_time": T.time() - _start_time
            })
            return Ok(response_key)
        else:
            err_detail = str(_result.unwrap_err())
            e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR, msg= err_detail)
            return Err(e)

    except Exception as e:
        _e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR, msg= str(e))
        return Err(_e)
