import os 
import sys
import time as T
import asyncio
import types
import zmq.asyncio 
import humanfriendly as HF
from dotenv import load_dotenv
from option import Result,Ok,Err,Some,NONE
from nanoid import generate as nanoid
# 
from activexendpoint.controllers.mw import manager_worker
# Activex 
from activex import Axo
from activex.endpoint import XoloEndpointManager,DistributedEndpoint
from activex.contextmanager import ActiveXContextManager
from activex.runtime.local import LocalRuntime
from activex.storage.data import MictlanXStorageService
# Mictlanx
from mictlanx.v4.client import Client
from mictlanx.utils.index import Utils as MictlanXUtils
from mictlanx.v4.summoner.summoner import Summoner
from mictlanx.logger.tezcanalyticx.tezcanalyticx import TezcanalyticXParams
from mictlanx.logger.log import Log
# ActivexEndpoitn
from activexendpoint.controllers import put_metadata,method_exeution,add_code
from activexendpoint.utils import install_packages,deploy_endpoint
import activexendpoint.utils as U
from activexendpoint.store import LocalKVStore
from activexendpoint.interfaces import Task,Heater
from activexendpoint.serde import DefaultSerde
import activexendpoint.constants as CONSTANTS
# globals()["Axo"] =Axo
ENV_FILE_PATH = os.environ.get("ENV_FILE_PATH",-1)
if not ENV_FILE_PATH == -1:
    load_dotenv(ENV_FILE_PATH)


AXO_CLASSES_REPOSITORY        = os.environ.get("AXO_CLASSES_REPOSITORY","/home/nacho/Programming/Python/activex-endpoint/classes")
AXO_ENDPOINT_ID               = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-0")
AXO_LOGGER_PATH               = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_LOGGER_WHEN               = os.environ.get("AXO_LOGGER_WHEN","h")
AXO_LOGGER_INTERVAL           = int(os.environ.get("AXO_LOGGER_INTERVAL","24"))
AXO_DEBUG                     = bool(int(os.environ.get("AXO_DEBUG","1")))
AXO_SINK_PATH                 = os.environ.get("AXO_SINK_PATH","/sink")
AXO_SOURCE_PATH               = os.environ.get("AXO_SOURCE_PATH","/source")
AXO_DATA_PATH                 = os.environ.get("AXO_DATA_PATH","/data")
AXO_ENDPOINT_IMAGE            = os.environ.get("AXO_ENDPOINT_IMAGE","nachocode/activex:endpoint")
AXO_ENDPOINT_DEPENDENCIES_STR = os.environ.get("AOX_ENDPOINT_DEPENDENCIES","")
AXO_ENDPOINT_DEPENDENCIES     = list(filter(lambda x: len(x) >0,  AXO_ENDPOINT_DEPENDENCIES_STR.split(";")))
AXO_PROTOCOL                  = os.environ.get("AXO_PROTOCOL","tcp")
AXO_PUB_SUB_PORT              = int(os.environ.get("AXO_PUB_SUB_PORT",16666))
AXO_REQ_RES_PORT              = int(os.environ.get("AXO_REQ_RES_PORT",16667))
AXO_HOSTNAME                  = os.environ.get("AXO_HOSTNAME","127.0.0.1")
AXO_SUBSCRIBER_HOSTNAME       = os.environ.get("AXO_SUBSCRIBER_HOSTNAME","*")
AXO_ENDPOINTS_STR             = os.environ.get("AXO_ENDPOINTS","").split(" ")
AXO_ENDPOINTS                 = list(filter(lambda x: len(x)>0, AXO_ENDPOINTS_STR))
AXO_HEATER_MAX_IDLE_TIME      = os.environ.get("AXO_HEATER_MAX_IDLE_TIME","1h")
# 
MICTLANX_XOLO_IP_ADDR         = os.environ.get("MICTLANX_XOLO_IP_ADDR","localhost")
MICTLANX_XOLO_API_VERSION     = os.environ.get("MICTLANX_XOLO_API_VERSION","3")
MICTLANX_XOLO_NETWORK         = os.environ.get("MICTLANX_XOLO_NETWORK","10.0.0.0/25")
MICTLANX_XOLO_PORT            = os.environ.get("MICTLANX_XOLO_PORT","15000")
MICTLANX_XOLO_PROTOCOL        = os.environ.get("MICTLANX_XOLO_PROTOCOL","http")
MICTLANX_XOLO_MODE            = os.environ.get("MICTLANX_XOLO_MODE","docker")

MICTLANX_BUCKET_ID = os.environ.get("MICTLANX_BUCKET_ID","activex")
MICTLANX_ROUTERS   = os.environ.get("MICTLANX_ROUTERS","mictlanx-router-0:localhost:60666")

routers                  = list(MictlanXUtils.routers_from_str(routers_str=MICTLANX_ROUTERS, separator=" "))
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
TEZCANALYTICX_ENABLED       = bool(int(os.environ.get("TEZCANALYTICS_ENABLED","0")))
# _____________________________________________________
if TEZCANALYTICX_ENABLED:
    TEZCANALYTICX = Some(
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
else:
    TEZCANALYTICX = NONE
loop = asyncio.get_event_loop()
asyncio.set_event_loop(loop=loop)


serde = DefaultSerde()

logger = Log(
    console_handler_filter=lambda x: AXO_DEBUG,
    create_folder=True,
    error_log=True,
    name=AXO_ENDPOINT_ID,
    path=AXO_LOGGER_PATH,
    when=AXO_LOGGER_WHEN,
    interval=AXO_LOGGER_INTERVAL,
)


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



mictlanx_client          = Client(
    client_id            = MICTLANX_CLIENT_ID,
    bucket_id            = MICTLANX_BUCKET_ID,
    debug                = MICTLANX_DEBUG,
    log_interval         = MICTLANX_LOG_INTERVAL,
    log_when             = MICTLANX_LOG_WHEN,
    log_output_path      = MICTLANX_LOG_OUTPUT_PATH,
    max_workers          = MICTLANX_MAX_WORKERS,
    routers              = routers,
    tezcanalyticx_params = TEZCANALYTICX
)

axcm = ActiveXContextManager(
    runtime= LocalRuntime(
        storage_service=Some(
            MictlanXStorageService.from_client(mictlanx_client)
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



install_packages(packages=AXO_ENDPOINT_DEPENDENCIES)


context = zmq.asyncio.Context()
req_rep_socket = context.socket(zmq.REP)


AXO_PUB_SUB_URI =  AXO_HOSTNAME if AXO_PUB_SUB_PORT == -1 else "{}:{}".format(AXO_SUBSCRIBER_HOSTNAME,AXO_PUB_SUB_PORT)
AXO_REQ_RES_URI =  AXO_HOSTNAME if AXO_REQ_RES_PORT == -1 else "{}:{}".format(AXO_HOSTNAME,AXO_REQ_RES_PORT)
req_rep_socket.bind("{}://{}".format(AXO_PROTOCOL,AXO_REQ_RES_URI))



        
heater = Heater(
    max_idle_time= AXO_HEATER_MAX_IDLE_TIME
)
store = LocalKVStore()





async def main_req_rep():
    global endpoint_manager
    logger.debug("Server - Listen on {}://{}".format(AXO_PROTOCOL,AXO_REQ_RES_URI))
    while True:
        try:
            _start_time = T.time()
            multipart   = await req_rep_socket.recv_multipart()
            msg_result  = U.from_multipart_to_task(multipart=multipart)

            if msg_result.is_err:
                logger.error({
                    "msg":str(msg_result.unwrap_err())
                })
                await req_rep_socket.send_multipart([b"activex",b"REQUEST.FAILED",CONSTANTS.ERROR_STATUS,b"{}",b""])
                continue
            task = msg_result.unwrap()
            logger.debug({
                "event":"TASK",
                "operation":task.operation,
                "task_id":task.task_id,
                "axo_bucket_id":task.get_axo_bucket_id(),
                "axo_key":task.get_axo_key(),
                "source_bucket_id":task.get_source_bucket_id(),
                "sink_bucket_id":task.get_sink_bucket_id(),
                "endpoint_id":task.get_endpoint_id(),
                "dependencies":task.get_dependencies(),
            })
            if heater.is_cold():
                logger.warning({
                    "event":"DRAIN.ENDPOINT",
                    "msg":"max_idle_timeout reached",
                    "max_idle_timeout":HF.format_timespan(heater.max_idle_time),
                })
                sys.exit(0)
            

            # topic       = task.topic
            operation   = task.operation
            # metadata    = task.metadata

            if operation =="PUT.METADATA":
                response = await put_metadata(
                    req_rep_socket= req_rep_socket,
                    h = heater,
                    endpoint_manager=endpoint_manager,
                    summoner=summoner,
                    task=task,
                    store=store
                )
                print("PUT.RESPONSE_RESPONSE",response)
                if response.is_ok:
                    print("PUT.METADATa.RESULT", response)
                else:
                    logger.error({
                        "event":"PUT.METADATA.FAILED",
                        "error":str(response.unwrap_err())
                    })
            elif operation == "ADD.CODE":
                res = add_code(
                    req_rep_socket= req_rep_socket,
                    h = heater,
                    endpoint_manager=endpoint_manager,
                    summoner=summoner,
                    task=task,
                    store=store
                )
                print("RES", res)
            elif operation == "ADD.CLASS.DEF":
                class_def_result = serde.deserialize(task.f)
                if class_def_result.is_ok:
                    class_def = class_def_result.unwrap()
                    globals()[class_def.__name__] = class_def
                    logger.info({"event":"ADD.CLASS.DEF","class_name": class_def.__name__})
                    await req_rep_socket.send_multipart([b"activex",b"CLASS.DEFINITION.ADDED",CONSTANTS.SUCCESS_STATUS,b"{}",b""])
                
            elif operation == "MW":
                await manager_worker(
                    store=store,
                    req_rep_socket=req_rep_socket,
                    serde=serde,
                    storage_service=mictlanx_client,
                    endpoint_manager=endpoint_manager,
                    heater=heater,
                    task=task
                )
            elif operation =="METHOD.EXEC":
                res = await method_exeution(
                    store=store,
                    req_rep_socket=req_rep_socket,
                    serde=serde,
                    storage_service=mictlanx_client,
                    endpoint_manager=endpoint_manager,
                    heater=heater,
                    task=task
                )
                print("METHOD_EXECUTION",res)
                # continue
            elif operation =="PING":
                heater.warm(task_id=task.task_id)
                logger.debug({
                    "envent":"PING",
                    "endpoint":AXO_ENDPOINT_ID
                })
                await req_rep_socket.send_multipart([b"activex",b"PONG",CONSTANTS.SUCCESS_STATUS,b"{}",b""])
                continue
            else:
                await req_rep_socket.send_multipart([b"activex",b"UKNOWN.OPERATION",CONSTANTS.ERROR_STATUS,b"{}",b""])
                continue
        except Exception as e:
            logger.error(str(e))
            await req_rep_socket.send_multipart([b"activex",b"INTERNAL.ENDPOINT.ERROR",CONSTANTS.ERROR_STATUS,b"{}",b""])


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
        if heater.is_cold():
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
