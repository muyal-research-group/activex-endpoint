import os 
import sys
import time as T
import asyncio
import zmq.asyncio 
import humanfriendly as HF
from dotenv import load_dotenv
from option import Some
# Axo
from axo.endpoint.manager import DistributedEndpointManager
from axo.endpoint.endpoint import DistributedEndpoint
from axo.enums import AxoOperationType
from axo.errors import AxoErrorType
# Mictlanx
from mictlanx import AsyncClient
from axo.log import Log
from mictlanx.services import Summoner

# ActivexEndpoitn
from axo_endpoint.endpoints import EndpointManager
import axo_endpoint.utils as U
from axo_endpoint.store import SimpleStore
from axo_endpoint.interfaces import Heater
from axo_endpoint.serde import DefaultSerde
from axo_endpoint.config import Config
import axo_endpoint.decentralized as Dx
from axo_endpoint.metrics import MetricCollector
import axo_endpoint.commands as CX

ENV_FILE_PATH = os.environ.get("ENV_FILE_PATH",-1)
if not ENV_FILE_PATH == -1:
    load_dotenv(ENV_FILE_PATH)





config            = Config()
serde             = DefaultSerde()
metrics_collector = MetricCollector(default_limit=config.AXO_METRICS_COLLECTOR_DEFAULT_LIMIT)

logger = Log(
    console_handler_filter = lambda x: config.AXO_DEBUG,
    error_log              = True,
    name                   = config.AXO_ENDPOINT_ID,
    path                   = config.AXO_LOGGER_PATH,
    when                   = config.AXO_LOGGER_WHEN,
    interval               = config.AXO_LOGGER_INTERVAL,
)


endpoints_global      = list(map(lambda x : DistributedEndpoint.from_str(endpoint_str=x), config.AXO_ENDPOINTS))
endpoints_global_dict = dict(list(map(lambda e: (e.endpoint_id, e), endpoints_global )))
endpoint_manager      = DistributedEndpointManager(
    endpoint_manager_id = config.AXO_ENDPOINT_ID, endpoints = endpoints_global_dict
)
endpoint_manager.add_endpoint(
    endpoint_id=config.AXO_ENDPOINT_ID,
    hostname=config.AXO_HOSTNAME,
    protocol=config.AXO_PROTOCOL,
    pubsub_port=config.AXO_PUB_SUB_PORT,
    req_res_port=config.AXO_REQ_RES_PORT
)



# routers = list(MictlanXUtils.routers_from_str(routers_str=config.MICTLANX_ROUTERS, separator=" ",protocol="http"))
mictlanx_client          = AsyncClient(
    client_id            = config.MICTLANX_CLIENT_ID,
    debug                = config.MICTLANX_DEBUG,
    log_interval         = config.MICTLANX_LOG_INTERVAL,
    log_when             = config.MICTLANX_LOG_WHEN,
    log_output_path      = config.MICTLANX_LOG_OUTPUT_PATH,
    max_workers          = config.MICTLANX_MAX_WORKERS,
    uri                  = config.MICTLANX_URI
)

# axcm = AxoContextManager(
#     runtime= LocalRuntime(
#         storage_service=Some(
#             MictlanXStorageService.from_client(mictlanx_client)
#         )
#     )
# )
# ______________________________________________________________
summoner = Summoner(
    ip_addr     = config.MICTLANX_SUMMONER_IP_ADDR,
    api_version = Some(config.MICTLANX_SUMMONER_API_VERSION),
    network     = Some(config.MICTLANX_SUMMONER_NETWORK), 
    port        = int(config.MICTLANX_SUMMONER_PORT),
    protocol    = config.MICTLANX_SUMMONER_PROTOCOL
)
endpoint_manager_x = EndpointManager(
    axo_endpoint_id = config.AXO_ENDPOINT_ID,
    summoner        = summoner,
    image           = config.AXO_ENDPOINT_IMAGE
)

endpoint_manager_x.add_endpoint(
    endpoint_id=config.AXO_ENDPOINT_ID,
    pub_sub_port=config.AXO_PUB_SUB_PORT,
    req_res_port=config.AXO_REQ_RES_PORT,
)


dependencies_installation_result = U.install_packages(packages=config.AXO_ENDPOINT_DEPENDENCIES)
if dependencies_installation_result.is_err:
    logger.warning({
        "event":"DEPENDENCIES.INSTALLATION.FAILED",
        "error":str(dependencies_installation_result.unwrap_err())
    })
    # sys.exit(1)


context = zmq.asyncio.Context()
req_rep_socket = context.socket(zmq.REP)


AXO_PUB_SUB_URI =  config.AXO_HOSTNAME if config.AXO_PUB_SUB_PORT == -1 else "{}:{}".format(config.AXO_SUBSCRIBER_HOSTNAME,config.AXO_PUB_SUB_PORT)
AXO_REQ_RES_URI =  config.AXO_HOSTNAME if config.AXO_REQ_RES_PORT == -1 else "{}:{}".format(config.AXO_HOSTNAME,config.AXO_REQ_RES_PORT)
req_rep_socket.bind("{}://{}".format(config.AXO_PROTOCOL,AXO_REQ_RES_URI))


heater = Heater(
    max_idle_time= config.AXO_HEATER_MAX_IDLE_TIME
)
store = SimpleStore()








async def main_req_rep(config:Config):
    global endpoint_manager
    logger.debug(f"Server - Listen on {config.AXO_PROTOCOL}://{AXO_REQ_RES_URI}")

    while True:
        t1 = T.time()

        extract_msg_result = await U.extract_task_envolope(socket=req_rep_socket)
        if extract_msg_result.is_err:
            continue

        (task,envelope,_) = extract_msg_result.unwrap()
        

        try:
            if heater.is_cold():
                logger.warning({
                    "event": "DRAIN.ENDPOINT",
                    "msg": "max_idle_timeout reached",
                    "max_idle_timeout": HF.format_timespan(heater.max_idle_time),
                    "duration":heater.get_current_active_time()
                })
                sys.exit(0)

            # Operation dispatch
            op = task.operation

            if op == AxoOperationType.PING:
                response = await CX.ping(socket=req_rep_socket,envolpe=envelope,task=task,heater=heater)
            elif op == AxoOperationType.PUT_METADATA:
                response = await CX.put_metadata_op(
                    socket           = req_rep_socket,
                    task             = task,
                    envelope         = envelope,
                    store            = store,
                    endpoint_manager = endpoint_manager,
                    heater           = heater,
                    summoner         = summoner,
                    config           =  config
                )

            elif op == AxoOperationType.METHOD_EXEC:
                response = await CX.method_exec_op(
                    socket=req_rep_socket,
                    summoner=summoner,
                    task=task,
                    envelope=envelope,
                    store=store,
                    serde=serde,
                    storage_service=mictlanx_client,
                    endpoint_manager=endpoint_manager,
                    heater=heater,
                )
            elif op == AxoOperationType.TASK_EXEC:
                response = await CX.task_exec_op(
                    socket           = req_rep_socket,
                    summoner         = summoner,
                    task             = task,
                    envelope         = envelope,
                    store            = store,
                    serde            = serde,
                    storage_service  = mictlanx_client,
                    endpoint_manager = endpoint_manager,
                    heater           = heater,
                )
            elif op == AxoOperationType.STREAM_EXEC:
                response = await CX.stream_exec_op(
                    socket=req_rep_socket,
                    summoner=summoner,
                    task=task,
                    envelope=envelope,
                    store=store,
                    serde=serde,
                    storage_service=mictlanx_client,
                    endpoint_manager=endpoint_manager,
                    heater=heater,
                )

            elif op == AxoOperationType.CREATE_ENDPOINT:
                response = await CX.create_endpoint(
                    socket=req_rep_socket,
                    task=task,
                    envelope=envelope,
                    store=store,
                    serde=serde,
                    storage_service=mictlanx_client,
                    endpoint_manager_x=endpoint_manager_x,
                    heater=heater,
                )

            else:
                await U.send_error(
                    socket=req_rep_socket,
                    operation = task.operation,
                    error_type=AxoErrorType.UNKNOWN_OPERATION,
                    message=f"Unkown operation: {op}",
                )
            logger.info({
                "event": "TASK.COMPLETED",
                "operation": op,
                "axo_bucket_id": task.get_axo_bucket_id(),
                "axo_key": task.get_axo_key(),
                "source_bucket_id": task.get_source_bucket_id(),
                "sink_bucket_id": task.get_sink_bucket_id(),
                "endpoint_id": task.get_endpoint_id(),
                "dependencies": task.get_dependencies(),
                **envelope.model_dump(),
                "task_id":task.task_id,
                "service_time": T.time() - t1
            })

        except Exception as e:
            await U.send_error(
                socket= req_rep_socket,
                task_id=task.task_id,
                operation=task.operation,
                error_type=AxoErrorType.INTERNAL_ERROR,
                message=str(e)
            )






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
    global config
    ctx = context  # you already created: zmq.asyncio.Context()

    task_reqrep = asyncio.create_task(main_req_rep(config=config))
    task_hb_pub = asyncio.create_task(Dx.heartbeat_publisher_task(ctx, config,metrics_collector))
    task_hb_sub = asyncio.create_task(Dx.heartbeat_subscriber_task(ctx,endpoint_manager, config))
    task_gc     = asyncio.create_task(Dx.neighbors_gc_task(config,endpoint_manager))
    task_heater = asyncio.create_task(run_heater())
    await asyncio.gather(task_reqrep, task_hb_pub, task_hb_sub, task_gc, task_heater)

    # await asyncio.gather(task1)

if __name__ == "__main__":

    loop = asyncio.get_event_loop()
    # asyncio.set_event_loop(loop=loop)
    loop.run_until_complete(main())
