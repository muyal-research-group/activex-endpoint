import json as J
import string
# from typing import Dict,Any,List
import time as T
import asyncio
import os
from typing import Dict, Any, Optional, Tuple,List
# 
from option import Err,Result,Ok,Option,Some,NONE
import zmq.asyncio 
# 
from axo_endpoint.config import Config
from axo_endpoint.interfaces import Heater,Task
from axo.endpoint.manager import DistributedEndpointManager
from axo.endpoint.endpoint import DistributedEndpoint
import axo_endpoint.utils as U
import axo_endpoint.constants  as CONSTANTS
from axo_endpoint.store import KVStore
from axo.core.models import MetadataX

from mictlanx.v4.summoner.summoner import Summoner
from axo.log import get_logger
from axo_endpoint.store.models import MetadataKey
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



async def __put_metadata(socket:zmq.Socket,store:KVStore,metadata:MetadataX,task_id:str = "")->Result[str, AxoError]:
    start_time = T.time()
    axo_key        = metadata.axo_key
    key = MetadataKey(id = axo_key,version=metadata.axo_version,alias=metadata.axo_alias)
    # print("METADATA",metadata)
    if axo_key == -1:
        e = AxoError.make(error_type=AxoErrorType.BAD_REQUEST, msg="Malformed request: It does not contain id field.")
        return Err(e)
    if store.exists(key=key):
        e = AxoError.make(error_type=AxoErrorType.ALREADY_EXISTS,msg="{} already exists".format(axo_key))
        return Err(e)
    store.put(key=key, value= metadata)
    rt = T.time() - start_time
    logger.info({
        "event":"PUT.METADATA",
        "key":axo_key,
        "_key":str(key),
        **metadata.model_dump(),
        "response_time":rt
    })
        # "{} {} {}".format("PUT.METADATA",key,rt))
    return Ok(axo_key)







def _extract_endpoint_id(task: Task) -> str:
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
                           endpoint_id: str,config:Config ) -> Result[Option[DistributedEndpoint],AxoError]:
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
        deploy_result = await U.__deploy_endpoint(
            summoner     = summoner,
            config=config,
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
    metadata:MetadataX,
    config:Config
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
        # metadata: Dict[str, Any] = task.metadata or {}
        # metadata = task
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

        key         = metadata.axo_key
        endpoint_id = _extract_endpoint_id(task)

        # Ensure endpoint exists (auto-deploy if needed)
        endpoint_result_maybe = await _ensure_endpoint(endpoint_manager, summoner, endpoint_id,config)
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

  
            try:
                put_res = await asyncio.wait_for(
                    endpointx.put(key=key, metadata=metadata),
                    timeout=config.AXO_METADATA_TIMEOUT
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
                return Ok(key)
            else:
                e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR, msg =str(put_res.unwrap_err()) )
                return Err(e)
        # Local path
        try:
            _result = await asyncio.wait_for(
                __put_metadata(socket=socket, store=store, metadata=metadata),
                timeout=config.AXO_METADATA_TIMEOUT
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
