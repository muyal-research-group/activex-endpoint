from axo_endpoint.interfaces import Heater,Task
from axo.endpoint.manager import DistributedEndpointManager
import axo_endpoint.utils as U
from mictlanx.v4.summoner.summoner import Summoner
from mictlanx.logger.log import Log
from typing import Dict,Any
import json as J
from axo import MetadataX
from option import Err,Result,Ok
from nanoid import generate as nanoid
import string
import zmq.asyncio 
import time as T
import axo_endpoint.constants  as CONSTANTS
from axo_endpoint.store import KVStore
# from axo_endpoint.i
# from axo_endpoint.dummy import add_dummy_module


import os
ALPHABET = string.ascii_lowercase+string.digits
AXO_ENDPOINT_IMAGE  = os.environ.get("AXO_ENDPOINT_IMAGE","nachocode/activex:endpoint")
AXO_ENDPOINT_ID     = os.environ.get("AXO_ENDPOINT_ID","axo-endpoint-0")
AXO_LOGGER_PATH     = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_LOGGER_WHEN     = os.environ.get("AXO_LOGGER_WHEN","h")
AXO_LOGGER_INTERVAL = int(os.environ.get("AXO_LOGGER_INTERVAL","24"))
AXO_DEBUG = bool(int(os.environ.get("AXO_DEBUG","1")))
logger = Log(
    console_handler_filter=lambda x: AXO_DEBUG,
    create_folder=True,
    error_log=True,
    name="activex.put.metadata",
    path=AXO_LOGGER_PATH,
    when=AXO_LOGGER_WHEN,
    interval=AXO_LOGGER_INTERVAL,
)


async def __put_metadata(req_rep_socket:zmq.Socket,store:KVStore,metadata:Dict[str,Any])->Result[str, Exception]:
    start_time = T.time()
    axo_key        = metadata.get("axo_key", -1)

    if axo_key == -1:
        error_obj = {"key":axo_key,"detail":"Malformed request: It does not contain id field."}
        await req_rep_socket.send_multipart([b"activex",b"BAD.REQUEST", J.dumps(error_obj).encode() ])
        logger.error("{} {}".format("BAD.REQUEST",axo_key))
        return Err(Exception(error_obj.get("detail","Uknown error")))
        # continue
    if store.exists(key=axo_key):
        error_obj = {"key":axo_key, "detail":"{} already exists".format(axo_key)}
        await req_rep_socket.send_multipart([b"activex",b"ALREADY.EXISTS", J.dumps(error_obj).encode() ])
        logger.error("{} {}".format("ALREADY.EXISTS",axo_key))
        return Err(Exception(error_obj.get("detail","Uknown error")))
    
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

async def put_metadata(
        store:KVStore,
        req_rep_socket:zmq.Socket,
        h:Heater,
        endpoint_manager:DistributedEndpointManager,
        summoner:Summoner,
        task:Task
):
    try:
        _start_time = T.time()
        # operation   = task.operation
        metadata    = task.metadata
        h.warm(task_id=task.task_id)
        # add_dummy_module(module_path=metadata.get("module","__main__"), class_name=metadata.get("class_name","__main__.Dummy"),dummy_class=class_def)
        # __________________________________________
        # Paso magico musical
        dependencies = task.get_dependencies()
        U.install_packages(packages=dependencies)
        # __________________________________________
        endpoint_id:str = metadata.get("endpoint_id",task.get_endpoint_id())
        exists          = endpoint_manager.exists(endpoint_id=endpoint_id)
        logger.debug({
            "event":"ENDPOINT.MANAGER",
            "endpoints":list(endpoint_manager.endpoints.keys()),
            "endpoint_id":AXO_ENDPOINT_ID,
            "current_endpoint_id":endpoint_id,
            "size":len(endpoint_manager.endpoints),
            "exists":exists
        })
        if not exists:
            deploy_endpoint_start_time = T.time()
            pubsub_port = endpoint_manager.get_available_pubsub_port()
            req_res_port= endpoint_manager.get_available_req_res_port()
            logger.debug({
                "event":"DEPLOY.ENDPOINT",
                "endpoint_id":endpoint_id,
                "pubsub_port":pubsub_port,
                "req_res_port":req_res_port
            })
            res_xolo = U.deploy_endpoint(
                summoner=summoner,
                endpoint_id=endpoint_id,
                pubsub_port=pubsub_port,
                req_res_port=req_res_port,
                dependencies=dependencies,
                image=AXO_ENDPOINT_IMAGE

            )
            if res_xolo.is_ok:
                response_xolo_endpoint = res_xolo.unwrap()
                endpoint_manager.add_endpoint(
                    endpoint_id=endpoint_id,
                    hostname=response_xolo_endpoint.ip_addr,
                    req_res_port=req_res_port,
                    pubsub_port=pubsub_port
                )
                logger.info({
                    "event":"DEPLOY.ENDPOINT",
                    "endpoint_id":endpoint_id,
                    "response_time":T.time() - deploy_endpoint_start_time
                })
            else:
                logger.error({
                    "error":"DEPLOY.ENDPOINT.FAILED",
                    "msg":str(res_xolo.unwrap_err()),
                    "endpoint_id":endpoint_id,
                    "req_res_port":req_res_port,
                    "pubsub_port":pubsub_port
                })

        if endpoint_id != AXO_ENDPOINT_ID:
            endpointx = endpoint_manager.get_endpoint(endpoint_id=endpoint_id)
            key = metadata.get("id","")
            res = endpointx.put(key=key, metadata=MetadataX(
                **metadata
            ))
            if res.is_ok:
                logger.info({
                    "event":"PUT.METADATA.COMPLETED",
                    **metadata,
                    "response_time":T.time() - _start_time
                })
                await req_rep_socket.send_multipart([b"activex",b"PUT.METADATA.SUCCESSED",CONSTANTS.SUCCESS_STATUS,b"{}",key.encode() ])
                return Ok(())
            raise Exception("{} fail to put.metadata {}".format(endpoint_id, key))
        else: 
        # __________________________________________
            _result = await __put_metadata(
                req_rep_socket=req_rep_socket,
                store=store,
                metadata=metadata
            )
        
            if _result.is_ok:
                response = _result.unwrap()
                logger.info({
                    "event":"PUT.METADATA.COMPLETED",
                    **metadata,
                    "response_time":T.time() - _start_time
                })
                await req_rep_socket.send_multipart([b"activex",b"PUT.METADATA.SUCCESSED",CONSTANTS.SUCCESS_STATUS,b"{}",response.encode()])
                return Ok(())
                # continue
            else:
                await req_rep_socket.send_multipart([b"activex",b"PUT.METADATA.FAILED",CONSTANTS.ERROR_STATUS,b"{}",b""])
                return Err(str(_result.unwrap_err()))
    except Exception as e:
        logger.error({
            "event":"PUT.METADATA.EXCEPTION",
            "error":str(e)
        })
        return Err(e)