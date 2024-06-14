# import aiofiles.os
import zmq.asyncio 
import string
import activexendpoint.utils as U
import aiofiles
import sys
import time as T
import os 
import cloudpickle as CP
import json as J
import humanfriendly as HF
from typing import List,Dict,Any,Callable
import logging
import asyncio
from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor

from abc import ABC,abstractmethod
from option import Result,Ok,Err,Option,Some,NONE
from activex.endpoint import XoloEndpointManager,DistributedEndpoint
from activex.storage.metadata import MetadataX
from activexendpoint.dummy import add_dummy_module, Dummy
from activexendpoint.utils import install_packages,deploy_endpoint
from mictlanx.v4.interfaces.responses import GetBytesResponse,GetMetadataResponse
from mictlanx.v4.client import Client
from mictlanx.utils.index import Utils as MictlanXUtils
from nanoid import generate as nanoid
from mictlanx.v4.summoner.summoner import Summoner
from mictlanx.logger.tezcanalyticx.tezcanalyticx import TezcanalyticXParams
from activexendpoint.store import LocalKVStore
from activexendpoint.interfaces import Task
from mictlanx.logger.log import Log
from dotenv import load_dotenv

ENV_FILE_PATH = os.environ.get("ENV_FILE_PATH",-1)
if not ENV_FILE_PATH == -1:
    load_dotenv(ENV_FILE_PATH)


AXO_ENDPOINT_ID = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-{}".format(nanoid(alphabet=string.ascii_lowercase+string.digits, size=8 )))
AXO_LOGGER_PATH = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_LOGGER_WHEN = os.environ.get("AXO_LOGGER_WHEN","h")
AXO_LOGGER_INTERVAL = int(os.environ.get("AXO_LOGGER_INTERVAL","24"))
AXO_DEBUG = bool(int(os.environ.get("AXO_DEBUG","1")))
AXO_SINK_PATH = os.environ.get("AXO_SINK_PATH","/sink")
AXO_SOURCE_PATH = os.environ.get("AXO_SOURCE_PATH","/source")
AXO_DATA_PATH = os.environ.get("AXO_DATA_PATH","/data")
# AXO_DATA_PATH = os.environ.get("AXO_DATA_PATH","/data")

loop = asyncio.get_event_loop()
asyncio.set_event_loop(loop=loop)



logger = Log(
    console_handler_filter=lambda x: AXO_DEBUG,
    create_folder=True,
    error_log=True,
    name=AXO_ENDPOINT_ID,
    path=AXO_LOGGER_PATH,
    when=AXO_LOGGER_WHEN,
    interval=AXO_LOGGER_INTERVAL,
)


AXO_ENDPOINT_IMAGE = os.environ.get("AXO_ENDPOINT_IMAGE","nachocode/activex:endpoint")
AXO_ENDPOINT_DEPENDENCIES = os.environ.get("AOX_ENDPOINT_DEPENDENCIES","")
AXO_ENDPOINT_DEPENDENCIES  = list(filter(lambda x: len(x) >0,  AXO_ENDPOINT_DEPENDENCIES.split(";")))
AXO_PROTOCOL =  os.environ.get("AXO_PROTOCOL","tcp")
AXO_PUB_SUB_PORT     = int(os.environ.get("AXO_PUB_SUB_PORT",16666))
AXO_REQ_RES_PORT     = int(os.environ.get("AXO_REQ_RES_PORT",16667))
AXO_HOSTNAME = os.environ.get("AXO_HOSTNAME","127.0.0.1")
AXO_SUBSCRIBER_HOSTNAME = os.environ.get("AXO_SUBSCRIBER_HOSTNAME","*")
AXO_ENDPOINTS = os.environ.get("AXO_ENDPOINTS","").split(" ")
AXO_ENDPOINTS = list(filter(lambda x: len(x)>0, AXO_ENDPOINTS))
endpoints_global = list(map(lambda x : DistributedEndpoint.from_str(endpoint_str=x), AXO_ENDPOINTS))
endpoints_global_dict = dict(list(map(lambda e: (e.endpoint_id, e), endpoints_global )))
endpoint_manager = XoloEndpointManager(endpoint_id=AXO_ENDPOINT_ID,endpoints=endpoints_global_dict)
endpoint_manager.add_endpoint(
    endpoint_id=AXO_ENDPOINT_ID,
    hostname=AXO_HOSTNAME,
    protocol=AXO_PROTOCOL,
    pubsub_port=AXO_PUB_SUB_PORT,
    req_res_port=AXO_REQ_RES_PORT
)


MICTLANX_XOLO_IP_ADDR = os.environ.get("MICTLANX_XOLO_IP_ADDR","localhost")
MICTLANX_XOLO_API_VERSION =  os.environ.get("MICTLANX_XOLO_API_VERSION","3")
MICTLANX_XOLO_NETWORK = os.environ.get("MICTLANX_XOLO_NETWORK","10.0.0.0/25")
MICTLANX_XOLO_PORT = os.environ.get("MICTLANX_XOLO_PORT","15000")
MICTLANX_XOLO_PROTOCOL = os.environ.get("MICTLANX_XOLO_PROTOCOL","http")
MICTLANX_XOLO_MODE = os.environ.get("MICTLANX_XOLO_MODE","docker")

MICTLANX_BUCKET_ID = os.environ.get("MICTLANX_BUCKET_ID","activex")
MICTLANX_ROUTERS = os.environ.get("MICTLANX_ROUTERS","mictlanx-router-0:localhost:60666")

routers = list(MictlanXUtils.routers_from_str(routers_str=MICTLANX_ROUTERS, separator=" "))
MICTLANX_CLIENT_ID       = os.environ.get("MICTLANX_CLIENT_ID", "activex-mictlanx-0")
MICTLANX_DEBUG           = bool(int(os.environ.get("MICTLANX_DEBUG","0")))
MICTLANX_LOG_INTERVAL    = int(os.environ.get("MICTLANX_LOG_INTERVAL","24"))
MICTLANX_LOG_WHEN        = os.environ.get("MICTLANX_LOG_WHEN","h")
MICTLANX_LOG_OUTPUT_PATH = os.environ.get("MICTLANX_LOG_OUTPUT_PATH","/log")
MICTLANX_MAX_WORKERS     = int(os.environ.get("MICTLANX_MAX_WORKERS","4"))

TEZCANALYTICX_FLUSH_TIMEOUT = os.environ.get("TEZCANALYTICX_FLUSH_TIMEOUT","10s")
TEZCANALYTICX_BUFFER_SIZE   = int(os.environ.get("TEZCANALYTICX_BUFFER_SIZE","100"))
TEZCANALYTICX_HOSTNAME      = os.environ.get("TEZCANALYTICX_HOSTNAME","localhost")
TEZCANALYTICX_LEVEL         = int(os.environ.get("TEZCANALYTICX_LEVEL","0"))
TEZCANALYTICX_PATH          = os.environ.get("TEZCANALYTICX_PATH","/api/v4/events")
TEZCANALYTICX_PORT          = int(os.environ.get("TEZCANALYTICX_PORT","45000"))
TEZCANALYTICX_PROTOCOL      = os.environ.get("TEZCANALYTICX_PROTOCOL","http")


mictlanx_client          = Client(
    client_id       = MICTLANX_CLIENT_ID,
    bucket_id       = MICTLANX_BUCKET_ID,
    debug           =  MICTLANX_DEBUG,
    log_interval    = MICTLANX_LOG_INTERVAL,
    log_when        = MICTLANX_LOG_WHEN,
    log_output_path = MICTLANX_LOG_OUTPUT_PATH,
    max_workers     = MICTLANX_MAX_WORKERS,
    routers              = routers, 
    tezcanalyticx_params = Some(
        TezcanalyticXParams(
            flush_timeout= TEZCANALYTICX_FLUSH_TIMEOUT,
            buffer_size=TEZCANALYTICX_BUFFER_SIZE,
            hostname=TEZCANALYTICX_HOSTNAME,
            level=TEZCANALYTICX_LEVEL,
            path=TEZCANALYTICX_PATH,
            port=TEZCANALYTICX_PORT,
            protocol=TEZCANALYTICX_PROTOCOL
        )
    ) 
)
# ______________________________________________________________
summoner = Summoner(
    ip_addr     = MICTLANX_XOLO_IP_ADDR,
    api_version = Some(MICTLANX_XOLO_API_VERSION),
    network     = Some(MICTLANX_XOLO_NETWORK), 
    port        = int(MICTLANX_XOLO_PORT),
    protocol    = MICTLANX_XOLO_PROTOCOL
)

ERROR_STATUS_INT = -1
number_of_bytes  = 4
ERROR_STATUS     = ERROR_STATUS_INT.to_bytes(byteorder="little",length=number_of_bytes,signed=True)
# 
SUCCESS_STATUS_INT = 0
SUCCESS_STATUS     = SUCCESS_STATUS_INT.to_bytes(byteorder="little",length=number_of_bytes,signed=True)


install_packages(packages=AXO_ENDPOINT_DEPENDENCIES)


context = zmq.asyncio.Context()
# pub_sub_socket = context.socket(zmq.SUB)
req_rep_socket = context.socket(zmq.REP)
# pub_sub_socket.setsockopt(zmq.SUBSCRIBE,b"activex")


AXO_PUB_SUB_URI =  AXO_HOSTNAME if AXO_PUB_SUB_PORT == -1 else "{}:{}".format(AXO_SUBSCRIBER_HOSTNAME,AXO_PUB_SUB_PORT)
AXO_REQ_RES_URI =  AXO_HOSTNAME if AXO_REQ_RES_PORT == -1 else "{}:{}".format(AXO_HOSTNAME,AXO_REQ_RES_PORT)

# waiting = float(os.environ.get("ACTIVEX_MIDDLEWARE_WAITING_TIME","1"))

# pub_sub_socket.connect("{}://{}".format(AXO_PROTOCOL,AXO_PUB_SUB_URI))
req_rep_socket.bind("{}://{}".format(AXO_PROTOCOL,AXO_REQ_RES_URI))



class Heater:
    def __init__(self,max_idle_time:str = "10m"):
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
        
h = Heater()

local_kv = LocalKVStore()


# Define a type hint for any callable

# Must be refactor as soon as possible
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
    key = metadata.get("axo_key", -1)
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




def serialize_fresult(result:Any)->bytes:
    try:
        x = J.dumps(result)
        return x.encode()
    except Exception as e:
        return CP.dumps(result)

async def method_execution(task:Task)->Result[Any, Exception]:
    start_time           = T.time()
    axo_key              = task.get_axo_key()
    axo_bucket_id        = task.get_axo_bucket_id()
    axo_source_bucket_id = task.get_source_bucket_id()
    axo_sink_bucket_id   = task.get_sink_bucket_id()

    try:
        if axo_key == -1:
            error_msg = "Key not found in metadata"
            logger.error({
                "msg":error_msg,
                "operation":"METHOD.EXEC"
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
            # continue

        maybe_mictlanx_metadata = local_kv.get(key=axo_key)
        if maybe_mictlanx_metadata.is_none:
            logger.warning({
                "event":"LOCAL.NOT.FOUND",
                "bucket_id":axo_bucket_id,
                "key":axo_key,
            })
            get_metadata_start_time = T.time()
            # Get from MictlanX
            get_metadata_result:Result[GetMetadataResponse, Exception]= mictlanx_client.get_metadata(key=axo_key,bucket_id=axo_bucket_id).result()
            if get_metadata_result.is_err:
                error_msg = "{} not found".format(axo_key)
                logger.error({
                    "error":error_msg,
                    "bucket_id":axo_bucket_id,
                    "key":axo_key
                })
                await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])
                return Err(Exception(error_msg))

            remote_metadata = get_metadata_result.unwrap()
            logger.info({
                "event":"GET.REMOTE.METADATA",
                "bucket_id":axo_bucket_id,
                "key":axo_key,
                "response_time":T.time() - get_metadata_start_time
            })
            put_metadata_start_time = T.time()
            # Put in metadata
            await put_metadata(topic=task.topic,operation=task.operation,metadata=remote_metadata.metadata.tags)
            maybe_mictlanx_metadata = Some(remote_metadata.metadata.tags)
        
        local_metadata = maybe_mictlanx_metadata.unwrap()
        module         = local_metadata.get("module",-1)
        name           = local_metadata.get("name",-1)
        add_dummy_module(module, name, Dummy)
        if module == -1 or name == -1:
            error_msg = "module or name attribute not found in tags"
            logger.error({
                "msg":error_msg,
                "bucket_id":axo_bucket_id,
                "key":axo_key,
                "operation":"METHOD.EXEC"
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
            # continue
        mictlanx_get_start_time =  T.time()
        obj_result_get_response :Result[GetBytesResponse,Exception]= mictlanx_client.get_with_retry(
            bucket_id=axo_bucket_id,
            key=axo_key
        )

        
        if obj_result_get_response.is_err:
            error_msg = "get_to_file failed"
            logger.error({
                "msg":error_msg, 
                "bucket_id":axo_bucket_id,
                "key":axo_key
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
        
        get_obj_response = obj_result_get_response.unwrap()
        obj_bytes        = get_obj_response.value
        logger.info({
            "event":"GET.OBJECT.REMOTE",
            "bucket_id":axo_bucket_id,
            "key":axo_key,
            "storage_service":"mictlanx",
            "response_time":T.time() - mictlanx_get_start_time
        })
        #
        des_start_time = T.time()
        obj              = CP.loads(obj_bytes)
        logger.info({
            "event":"DESERALIZATION",
            "bucket_id":axo_bucket_id,
            "key":axo_key,
            "response_time":T.time() - des_start_time
        })
        # ____________________________________________________
        logger.debug({
            "event":"GET.SOURCE.DATA",
            "axo_source_bucket_id":axo_source_bucket_id,
            "source_keys":task.get_sink_keys()
        })
        # Pattern
        # Get bucket
        axo_sink_path_source_bucket_id_path = "{}/{}".format(AXO_SINK_PATH,axo_source_bucket_id)
        axo_sink_path_sink_bucket_id_path   = "{}/{}".format(AXO_SINK_PATH,axo_sink_bucket_id)
        os.makedirs(axo_sink_path_sink_bucket_id_path)

        bucket_get = mictlanx_client.get_bucket_data(bucket_id=axo_source_bucket_id, output_folder_path=axo_sink_path_source_bucket_id_path )
        if bucket_get.is_err:
            error_msg = "get_bucket_failed"
            logger.error({
                "msg":error_msg, 
                "axo_source_bucket_id":axo_source_bucket_id,
                "axo_sink_path_source_bucket_id_path":axo_sink_path_source_bucket_id_path
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
        logger.debug({
            "event":"GET.BUCKET.DATA",
            "axo_source_bucket_id":axo_source_bucket_id,
            "axo_sink_path_source_bucket_id_path":axo_sink_path_source_bucket_id_path
        })
        axo_source_files = bucket_get.unwrap()
        for axo_source_path in axo_source_files:

            axo_sink_key  = nanoid(alphabet=string.ascii_lowercase+string.digits,size=16)
            axo_sink_path = "{}/{}".format(axo_sink_path_sink_bucket_id_path,axo_sink_key)
            logger.debug({
                "event":"EXECUTING.METHOD",
                "fname":task.metadata.get("fname",""),
                "axo_source_bucket_id":axo_source_bucket_id,
                "axo_source_path":axo_source_path,
                "axo_sink_path_source_bucket_id_path":axo_sink_path_source_bucket_id_path,
                # 
                "axo_sink_path_sink_bucket_id_path":axo_sink_path_sink_bucket_id_path,
                "axo_sink_path":axo_sink_path,
                "axo_sink_key":axo_sink_key,
            })
            # 
            fkwargs = {
                **task.fkwargs,
                "axo_source_path":axo_source_path,
                "axo_sink_path_sink_bucket_id_path":axo_sink_path_sink_bucket_id_path,
                "axo_sink_path":axo_sink_path,
                "axo_sink_key":axo_sink_key
            }
            res              = task.f(obj,*task.fargs, **fkwargs)
        # ___________________________________________________
            logger.debug({
                "event":"SHOW.RESULT",
                "n":len(axo_source_files),
                "axo_source_bucket_id":axo_source_bucket_id,
                "axo_source_path":axo_source_path,
                "axo_sink_path_source_bucket_id_path":axo_sink_path_source_bucket_id_path,
                "axo_sink_path":axo_sink_path,
                "axo_sink_key":axo_sink_key,
                "res":str(res)
            })
            if not res == None:
                result_bytes= serialize_fresult(result=res)
                axo_fsink_key = nanoid(alphabet=string.ascii_lowercase+string.digits, size=16)
                put_result   = mictlanx_client.put_chunked(
                    chunks=U.byte_generator(result_bytes),
                    bucket_id=axo_sink_bucket_id,
                    key=axo_fsink_key,
                    tags={
                        "parent_object_id":axo_key,
                    }
                )
                
                # print("PUT+RESULT",put_result)
                if put_result.is_err:
                    logger.error({
                        "event":"PUT.CHUNKED.FAILED",
                        "bucket_id":axo_bucket_id,
                        "key":axo_fsink_key,
                    })
        
            logger.info({
                "event":"METHOD.EXEC.COMPLETED",
                "axo_source_bucket_id":axo_source_bucket_id,
                "axo_source_path":axo_source_path,
                # 
                "axo_sink_bucket_id":axo_sink_bucket_id,
                "axo_bucket_sink_path":axo_sink_path_source_bucket_id_path,
                "axo_sink_path":axo_sink_path,
                "axo_sink_key":axo_sink_key,
                "response_time": T.time()- start_time
            })

        result_metadata = J.dumps({}).encode(encoding="utf-8")
        
        await req_rep_socket.send_multipart([b"activex",b"METHOD.EXEC.COMPLETED",SUCCESS_STATUS,result_metadata, result_bytes])
    except Exception as e:
        error_msg = "Uknown error"
        logger.error({
            "msg":error_msg,
            "operation":"METHOD.EXEC",
            "raw_error":str(e)
        })
        await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",ERROR_STATUS,b"{}",b""])
        return Err(Exception(error_msg))









async def main_req_rep():
    global endpoint_manager
    logger.debug("Server - Listen on {}://{}".format(AXO_PROTOCOL,AXO_REQ_RES_URI))
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
            task = msg_result.unwrap()
            logger.debug({
                "event":"TASK",
                "operation":task.operation,
                "task_id":task.task_id,
                "axo_bucket_id":task.get_axo_bucket_id(),
                "axo_key":task.get_axo_key(),
                "source_bucket_id":task.get_source_bucket_id(),
                # "sink_key":task.get_source_key(),
                "sink_keys":task.get_source_keys(),
                "sink_bucket_id":task.get_sink_bucket_id(),
                # "sink_key":task.get_sink_key(),
                "sink_keys":task.get_sink_keys(),
                "endpoint_id":task.get_endpoint_id(),
                "dependencies":task.get_dependencies()
            })
            if h.is_cold():
                logger.warning({
                    "event":"DRAIN.ENDPOINT"
                })
                sys.exit(0)
            

            topic       = task.topic
            operation   = task.operation
            metadata    = task.metadata

            if operation =="PUT.METADATA":
                h.warm(task_id=task.task_id)
                # __________________________________________
                # Paso magico musical
                sink_bucket_id = task.get_sink_bucket_id()
                dependencies = task.get_dependencies()
                # sink_bucket_id = metadata.get("sink_bucket_id","")
                # dependencies = metadata.get("dependencies",[])
                install_packages(packages=dependencies)
                # __________________________________________
                endpoint_id:str = metadata.get("endpoint_id",task.get_endpoint_id())
                exists = endpoint_manager.exists(endpoint_id=endpoint_id)
                logger.debug({
                    "event":"ENDPOINT.MANAGER",
                    "endpoints":str(endpoint_manager.endpoints),
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
                    res_xolo = deploy_endpoint(
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
                    logger.info({
                        "event":"PUT.METADATA.COMPLETED",
                        **metadata,
                        "response_time":T.time() - _start_time
                    })
                    await req_rep_socket.send_multipart([b"activex",b"PUT.METADATA.SUCCESSED",SUCCESS_STATUS,b"{}",key.encode() ])
                else: 
                # __________________________________________
                    _result = (await put_metadata(topic=topic, operation=operation,metadata=metadata))
                    if _result.is_ok:
                        response = _result.unwrap()
                        logger.info({
                            "event":"PUT.METADATA.COMPLETED",
                            **metadata,
                            "response_time":T.time() - _start_time
                        })
                        await req_rep_socket.send_multipart([b"activex",b"PUT.METADATA.SUCCESSED",SUCCESS_STATUS,b"{}",response.encode()])
                        continue
                    else:
                        await req_rep_socket.send_multipart([b"activex",b"PUT.METADATA.FAILED",ERROR_STATUS,b"{}",b""])


            elif operation =="METHOD.EXEC":
                h.warm(task_id=task.task_id)
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
                result = await method_execution(task)
                continue
            elif operation =="PING":
                h.warm(task_id=task.task_id)
                logger.debug({
                    "envent":"PING",
                    "endpoint":AXO_ENDPOINT_ID
                })
                await req_rep_socket.send_multipart([b"activex",b"PONG",SUCCESS_STATUS,b"{}",b""])
                continue
            else:
                await req_rep_socket.send_multipart([b"activex",b"UKNOWN.OPERATION",ERROR_STATUS,b"{}",b""])
                continue
        except Exception as e:
            logger.error(str(e))
            await req_rep_socket.send_multipart([b"activex",b"INTERNAL.ENDPOINT.ERROR",ERROR_STATUS,b"{}",b""])


# async def main_sub():
#     logger.debug("Subscriber - Listen on {}://{}".format(AXO_PROTOCOL,AXO_PUB_SUB_URI))
    # while True: 
#         try:
#             msg = await pub_sub_socket.recv_multipart()
#             print("msg",msg)
        # except Exception as e:
            # logger.error(e)


    
q = asyncio.Queue(maxsize=int(os.environ.get("AXO_SYNC_MAXSIZE_QUEUE","100")))

async def async_walk(directory):
    global loop
    # loop = asyncio.get_running_loop()
    for dirpath, dirnames, filenames in await loop.run_in_executor(None, os.walk, directory):
        yield dirpath, dirnames, filenames

async def list_files(directory):
    async for dirpath, dirnames, filenames in async_walk(directory):
        for filename in filenames:
            print(os.path.join(dirpath, filename))
   

async def run_file_sync():
    x  =os.environ.get("AXO_SYNC_MAX_IDLE_TIME","20s")
    AXO_SYNC_MAX_IDLE_TIME = HF.parse_timespan(x)
    logger.debug({
        "event":"AXO.FILE.SYNC",
        "max_idle_time":x
    })
    
    while True:
        try:
            item =  await asyncio.wait_for(q.get(), timeout=AXO_SYNC_MAX_IDLE_TIME)
        except asyncio.TimeoutError as e:
            logger.warning({
                "event":"max idle time reached",
                "max_idle_time":x
            })
        except Exception as e: 
            logger.error(str(e))
        finally:
            await asyncio.sleep(delay=AXO_SYNC_MAX_IDLE_TIME)



async def run_heater():
    x  =os.environ.get("HEATER_TICK_TIME","30s")
    HEATER_TICK_TIME = HF.parse_timespan(x)
    logger.debug({
        "event":"HEATER.STARTING",
        "MAX_TICK_TIME":x
    })
    while True:
        if h.is_cold():
            logger.warning({
                "event":"ENDPOINT.IS.COLD",
            })

        await asyncio.sleep(delay=HEATER_TICK_TIME)

        

async def main():

    task1 = asyncio.create_task(main_req_rep())
    task2 = asyncio.create_task(run_file_sync())
    # task2 = asyncio.create_task(run_heater())
    await asyncio.gather(task1,task2)

if __name__ == "__main__":
    loop.run_until_complete(main())
    # asyncio.run(main=main())
