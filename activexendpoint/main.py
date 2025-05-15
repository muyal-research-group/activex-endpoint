import os 
import sys
import time as T
import asyncio
import zmq.asyncio 
import humanfriendly as HF
from dotenv import load_dotenv
from option import Some
# 
from activexendpoint.controllers.mw import manager_worker
# Activex 
from axo.endpoint.manager import DistributedEndpointManager
from axo.endpoint.endpoint import DistributedEndpoint
from axo.contextmanager import ActiveXContextManager
from axo.runtime.local import LocalRuntime
from axo.storage.data import MictlanXStorageService
# Mictlanx
from mictlanx.v4.asyncx import AsyncClient
from mictlanx.logger.log import Log
from mictlanx.utils.index import Utils as MictlanXUtils
from mictlanx.v4.summoner.summoner import Summoner

# ActivexEndpoitn
from activexendpoint.endpoints import EndpointManager
from activexendpoint.controllers import put_metadata,method_exeution,elasticity
from activexendpoint.utils import install_packages
import activexendpoint.utils as U
from activexendpoint.store import LocalKVStore
from activexendpoint.interfaces import Heater
from activexendpoint.serde import DefaultSerde
import activexendpoint.constants as CONSTANTS
from activexendpoint.config import Config
# globals()["Axo"] =Axo
ENV_FILE_PATH = os.environ.get("ENV_FILE_PATH",-1)
if not ENV_FILE_PATH == -1:
    load_dotenv(ENV_FILE_PATH)


config = Config()
loop = asyncio.get_event_loop()
asyncio.set_event_loop(loop=loop)


serde = DefaultSerde()

logger = Log(
    console_handler_filter=lambda x: config.AXO_DEBUG,
    create_folder=True,
    error_log=True,
    name=config.AXO_ENDPOINT_ID,
    path=config.AXO_LOGGER_PATH,
    when=config.AXO_LOGGER_WHEN,
    interval=config.AXO_LOGGER_INTERVAL,
)


endpoints_global = list(map(lambda x : DistributedEndpoint.from_str(endpoint_str=x), config.AXO_ENDPOINTS))
endpoints_global_dict = dict(list(map(lambda e: (e.endpoint_id, e), endpoints_global )))
endpoint_manager = DistributedEndpointManager(
    endpoint_manager_id=config.AXO_ENDPOINT_ID,endpoints=endpoints_global_dict
)
endpoint_manager.add_endpoint(
    endpoint_id=config.AXO_ENDPOINT_ID,
    hostname=config.AXO_HOSTNAME,
    protocol=config.AXO_PROTOCOL,
    pubsub_port=config.AXO_PUB_SUB_PORT,
    req_res_port=config.AXO_REQ_RES_PORT
)



routers = list(MictlanXUtils.routers_from_str(routers_str=config.MICTLANX_ROUTERS, separator=" ",protocol="https"))
mictlanx_client          = AsyncClient(
    client_id            = config.MICTLANX_CLIENT_ID,
    debug                = config.MICTLANX_DEBUG,
    log_interval         = config.MICTLANX_LOG_INTERVAL,
    log_when             = config.MICTLANX_LOG_WHEN,
    log_output_path      = config.MICTLANX_LOG_OUTPUT_PATH,
    max_workers          = config.MICTLANX_MAX_WORKERS,
    routers              = routers,
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
    ip_addr     = config.MICTLANX_XOLO_IP_ADDR,
    api_version = Some(config.MICTLANX_XOLO_API_VERSION),
    network     = Some(config.MICTLANX_XOLO_NETWORK), 
    port        = int(config.MICTLANX_XOLO_PORT),
    protocol    = config.MICTLANX_XOLO_PROTOCOL
)
endpoint_manager_x = EndpointManager(
    summoner = summoner,
    image=config.AXO_ENDPOINT_IMAGE
)
if config.AXO_ENDPOINT_ID == "activex-endpoint-0":
    res = endpoint_manager_x.clean_endpoints()

endpoint_manager_x.add_endpoint(
    endpoint_id=config.AXO_ENDPOINT_ID,
    pub_sub_port=config.AXO_PUB_SUB_PORT,
    req_res_port=config.AXO_REQ_RES_PORT,
)


install_packages(packages=config.AXO_ENDPOINT_DEPENDENCIES)


context = zmq.asyncio.Context()
req_rep_socket = context.socket(zmq.REP)


AXO_PUB_SUB_URI =  config.AXO_HOSTNAME if config.AXO_PUB_SUB_PORT == -1 else "{}:{}".format(config.AXO_SUBSCRIBER_HOSTNAME,config.AXO_PUB_SUB_PORT)
AXO_REQ_RES_URI =  config.AXO_HOSTNAME if config.AXO_REQ_RES_PORT == -1 else "{}:{}".format(config.AXO_HOSTNAME,config.AXO_REQ_RES_PORT)
req_rep_socket.bind("{}://{}".format(config.AXO_PROTOCOL,AXO_REQ_RES_URI))



        
heater = Heater(
    max_idle_time= config.AXO_HEATER_MAX_IDLE_TIME
)
store = LocalKVStore()




async def main_req_rep():
    global endpoint_manager
    logger.debug("Server - Listen on {}://{}".format(config.AXO_PROTOCOL,AXO_REQ_RES_URI))
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
            # print("OPERATION",operation)
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
                if response.is_err:
                    logger.error({
                        "event":"PUT.METADATA.FAILED",
                        "error":str(response.unwrap_err())
                    })
                    await req_rep_socket.send_multipart([b"activex",b"error",CONSTANTS.ERROR_STATUS, b"{}",b""])
            elif operation == "MW":
                await manager_worker(
                    store=store,
                    req_rep_socket=req_rep_socket,
                    serde=serde,
                    storage_service=mictlanx_client,
                    endpoint_manager=endpoint_manager,
                    heater=heater,
                    task=task,
                    config= config
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
            elif operation == "ELASTICITY":
                res = await elasticity(
                    store=store,
                    req_rep_socket=req_rep_socket,
                    serde=serde,
                    storage_service=mictlanx_client,
                    endpoint_manager=endpoint_manager_x,
                    heater=heater,
                    task=task,
                    # summoner = summoner,
                )
            elif operation =="PING":
                heater.warm(task_id=task.task_id)
                logger.debug({
                    "envent":"PING",
                    "endpoint":config.AXO_ENDPOINT_ID
                })
                await req_rep_socket.send_multipart([b"activex",b"PONG",CONSTANTS.SUCCESS_STATUS,b"{}",b""])
                continue
            else:
                await req_rep_socket.send_multipart([b"activex",b"UKNOWN.OPERATION",CONSTANTS.ERROR_STATUS,b"{}",b""])
                continue
        except Exception as e:
            logger.error(str(e))
            await req_rep_socket.send_multipart([b"activex",b"INTERNAL.ENDPOINT.ERROR",CONSTANTS.ERROR_STATUS,b"{}",b""])



    
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
   

async def run_heater():
    HEATER_TICK_TIME = HF.parse_timespan(config.AXO_HEATER_TICK_TIME)
    logger.debug({
        "event":"HEATER.STARTING",
        "MAX_TICK_TIME":config.AXO_HEATER_TICK_TIME
    })
    while True:
        if heater.is_cold():
            logger.warning({
                "event":"ENDPOINT.IS.COLD",
            })

        await asyncio.sleep(delay=HEATER_TICK_TIME)

        

async def main():

    task1 = asyncio.create_task(main_req_rep())
    await asyncio.gather(task1)

if __name__ == "__main__":
    loop.run_until_complete(main())
