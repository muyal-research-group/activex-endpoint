import os 
import sys
import time as T
import asyncio
import zmq.asyncio 
import humanfriendly as HF
from dotenv import load_dotenv
from option import Some,Result,Ok,Err
from typing import List,Tuple
# Axo
from axo.endpoint.manager import DistributedEndpointManager
from axo.endpoint.endpoint import DistributedEndpoint
from axo.contextmanager import AxoContextManager
from axo.runtime.local import LocalRuntime
from axo.storage.data import MictlanXStorageService
from axo.core.models import MetadataX
from axo.models import AxoRequestEnvelope
from axo.enums import AxoOperationType
from axo.errors import AxoErrorType,AxoError
# Mictlanx
from mictlanx.v4.asyncx import AsyncClient
from mictlanx.logger.log import Log
from mictlanx.utils.index import Utils as MictlanXUtils
from mictlanx.v4.summoner.summoner import Summoner

# ActivexEndpoitn
from axo_endpoint.endpoints import EndpointManager
from axo_endpoint.controllers import put_metadata,method_exeution,elasticity
from axo_endpoint.utils import install_packages
import axo_endpoint.utils as U
from axo_endpoint.store import SimpleStore
from axo_endpoint.interfaces import Heater
from axo_endpoint.serde import DefaultSerde
from axo_endpoint.config import Config
from axo_endpoint.interfaces import Task

ENV_FILE_PATH = os.environ.get("ENV_FILE_PATH",-1)
if not ENV_FILE_PATH == -1:
    load_dotenv(ENV_FILE_PATH)



config = Config()

serde = DefaultSerde()

logger = Log(
    console_handler_filter = lambda x: config.AXO_DEBUG,
    create_folder          = True,
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



routers = list(MictlanXUtils.routers_from_str(routers_str=config.MICTLANX_ROUTERS, separator=" ",protocol="http"))
mictlanx_client          = AsyncClient(
    client_id            = config.MICTLANX_CLIENT_ID,
    debug                = config.MICTLANX_DEBUG,
    log_interval         = config.MICTLANX_LOG_INTERVAL,
    log_when             = config.MICTLANX_LOG_WHEN,
    log_output_path      = config.MICTLANX_LOG_OUTPUT_PATH,
    max_workers          = config.MICTLANX_MAX_WORKERS,
    routers              = routers,
)

axcm = AxoContextManager(
    runtime= LocalRuntime(
        storage_service=Some(
            MictlanXStorageService.from_client(mictlanx_client)
        )
    )
)
# ______________________________________________________________
summoner = Summoner(
    ip_addr     = config.MICTLANX_SUMMONER_IP_ADDR,
    api_version = Some(config.MICTLANX_SUMMONER_API_VERSION),
    network     = Some(config.MICTLANX_SUMMONER_NETWORK), 
    port        = int(config.MICTLANX_SUMMONER_PORT),
    protocol    = config.MICTLANX_SUMMONER_PROTOCOL
)
endpoint_manager_x = EndpointManager(
    summoner = summoner,
    image=config.AXO_ENDPOINT_IMAGE
)

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
store = SimpleStore()





async def ping(socket:zmq.asyncio.Socket,task:Task,envolpe:AxoRequestEnvelope):
    try:

        t1 = T.time()
        heater.warm(task_id=task.task_id)
        # await send_success(req_rep_socket, "PONG")
        logger.info({
            "event":task.operation, 
            "msg_id":envolpe.msg_id,
            "task_id":task.task_id,
            "endpoint": config.AXO_ENDPOINT_ID,
            "service_time":T.time()-t1
        })
        await U.send_ok(
            socket             = socket,
            operation          = task.operation,
            task_id            = task.task_id,
            msg_id             = envolpe.msg_id,
            envelope_overrides = {},
            payload_frames     = [],
        )
        return Ok(None)
    except Exception as e:
        return Err(e)
    


async def put_metadata_op(
    *,
    socket: zmq.asyncio.Socket,
    task: Task,
    # metadata:MetadataX,
    envelope: AxoRequestEnvelope,
    store: SimpleStore,
    endpoint_manager: DistributedEndpointManager,
    heater: Heater,
    summoner: Summoner,
    config:Config
) -> Result[None, Exception]:
    try:
        t0 = T.time()
        heater.warm(task_id=task.task_id)

        metadata         = envelope.get_metadatax()
        res = await put_metadata(
            store            = store,
            socket           = socket,           # kept for signature compatibility, but controller should not send
            h                = heater,
            endpoint_manager = endpoint_manager,
            summoner         = summoner,
            task             = task,
            config           = config,
            metadata         = metadata
        )
        print("PUT_RES",res)

        if res.is_err:
            err = res.unwrap_err()
            await U.send_error_axo(
                socket    = socket,
                operation = task.operation,
                task_id   = task.task_id,
                msg_id    = envelope.msg_id,
                error     = err
            )
            return Err(err)

        # Optionally echo stored key / object info in reply envelope
        await U.send_ok(
            socket=socket,
            operation=task.operation,
            task_id=task.task_id,
            envelope_overrides={
                "axo_uri": envelope.axo_uri,  
                "method": None,
            },
        )

        logger.info({
            "event": task.operation,
            "task_id": task.task_id,
            "object_id": envelope.axo_uri,
            "response_time": T.time() - t0,
        })
        return Ok(None)

    except Exception as e:
        await U.send_error(
            socket    = socket,
            operation = task.operation,
            task_id   = task.task_id,
            message   = str(e),
            error_type=AxoErrorType.INTERNAL_ERROR
        )
        return Err(e)


# ------------------------------------------------------------------------------
# METHOD.EXEC
# ------------------------------------------------------------------------------
async def method_exec_op(
    *,
    socket: zmq.asyncio.Socket,
    summoner:Summoner,
    task: Task,
    envelope: AxoRequestEnvelope,
    store: SimpleStore,
    serde: DefaultSerde,
    storage_service: AsyncClient,
    endpoint_manager: DistributedEndpointManager,
    heater: Heater,
) -> Result[None, Exception]:
    """
    Controller should return:
        Ok( (result_obj, patch_dict_or_none, post_version_or_none) )
    The handler serializes result/patch into payload frames and replies with:
        [MAGIC, PROTO, "METHOD.EXEC.REPLY", JSON_CT, reply_envelope_json, result_pickle, [patch_pickle]]
    """
    try:
        t0 = T.time()
        heater.warm(task_id=task.task_id)

        # Call your execution controller (it must NOT send on the socket)
        # Expected return shape for success:
        #    Ok( (result_obj, patch_dict_or_none, post_version_or_none) )
        exec_res = await method_exeution(
            endpoint_manager = endpoint_manager,
            summoner         = summoner,
            heater           = heater,
            serde            = serde,
            storage_service  = storage_service,
            store            = store,
            req_rep_socket   = socket,           # kept for signature; do not use to send
            task             = task,
            envelope         = envelope,
            config           = config,
        )
        print("EXC+RES",exec_res)

        if exec_res.is_err:
            # err_msg = str(exec_res.unwrap_err())
            await U.send_error_axo(
                socket    = socket,
                operation = AxoOperationType.METHOD_EXEC,
                task_id   = task.task_id,
                error=exec_res.unwrap_err(),
                # message=err_msg,
           
                # payload_frames=[],
            )
            return Err(exec_res.unwrap_err())
            # return Err(Exception(err_msg))


        # await U.send_ok(
        #     socket=socket,
        #     operation=envelope.operation,
        #     task_id=envelope.task_id,
        #     msg_id=envelope.msg_id,
        #     envelope_overrides={
        #         "axo_uri": envelope.axo_uri,
        #         "method": envelope.method,
        #         "axo_version": envelope.axo_version,
        #     }
        # )

        logger.info({
            "event": "METHOD.EXEC.REPLY",
            "task_id": task.task_id,
            "object_id": envelope.axo_uri,
            "method": envelope.method,
            "axo_version": envelope.axo_version,
            # "post_version": post_version,
            "response_time": T.time() - t0,
        })
        return Ok(None)

    except Exception as e:
        _e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR,msg=str(e))
        await U.send_error_axo(socket=socket, operation=envelope.operation,task_id=envelope.task_id,msg_id = envelope.msg_id,error = _e)
        return Err(_e)


# ------------------------------------------------------------------------------
# ELASTICITY (scale up/down / replicate endpoints)
# ------------------------------------------------------------------------------
async def create_endpoint(
    *,
    socket: zmq.asyncio.Socket,
    task: Task,
    envelope: AxoRequestEnvelope,
    store: SimpleStore,
    serde: DefaultSerde,
    storage_service: AsyncClient,
    endpoint_manager_x: EndpointManager,   # your specialized manager for elasticity
    heater: Heater,
) -> Result[None, Exception]:
    try:
        t0 = T.time()
        heater.warm(task_id=task.task_id)

        # Call your elasticity controller (must not send on its own)
        res = await elasticity(
            store=store,
            req_rep_socket=socket,        # keep for signature; avoid sending inside
            serde=serde,
            storage_service=storage_service,
            endpoint_manager=endpoint_manager_x,
            heater=heater,
            task=task,
        )

        if res.is_err:
            err_msg = str(res.unwrap_err())
            await U.send_error(
                socket     = socket,
                operation  = AxoOperationType.CREATE_ENDPOINT,
                task_id    = task.task_id,
                error_type = AxoErrorType.INTERNAL_ERROR,
                message    = err_msg
            )
            return Err(Exception(err_msg))

        await U.send_ok(
            socket             = socket,
            operation          = AxoOperationType.CREATE_ENDPOINT,
            task_id            = task.task_id,
            envelope_overrides = {
                "axo_uri": envelope.axo_uri,
            },
        )

        logger.info({
            "event": "ELASTICITY.REPLY",
            "task_id": task.task_id,
            "object_id": envelope.axo_uri,
            "response_time": T.time() - t0,
        })
        return Ok(None)

    except Exception as e:
        await U.send_error(
            socket     = socket,
            operation  = AxoOperationType.CREATE_ENDPOINT,
            task_id    = task.task_id,
            error_type = AxoErrorType.INTERNAL_ERROR,
            message    = str(e)
        )
        return Err(e)



async def extract_task_envolope(socket:zmq.asyncio.Socket, )->Result[Tuple[Task,AxoRequestEnvelope,List[bytes]],AxoError]:
    
    try:
        multipart = await socket.recv_multipart()
        _start_time = T.time()
        # Parse task
        msg_result = U.from_multipart_to_task_and_envelope(multipart=multipart)
        if msg_result.is_err:
            e = msg_result.unwrap_err()
            await U.send_error_axo(
                socket    = socket,
                operation = "UNKNOWN",
                task_id   = "",
                error     = e
            )
            return Err(e)

        (task,envelope, frames) = msg_result.unwrap()
        logger.debug({
            "event": "TASK.RECEIVED",
            "operation": task.operation,
            "task_id": task.task_id,
            **envelope.model_dump(),
            "service_time":T.time()-_start_time
        })
        return Ok((task,envelope,frames))
    except Exception as e:
        await U.send_error(
            socket     = req_rep_socket,
            operation  = AxoOperationType.UNKNOWN,
            task_id    = None,
            error_type = AxoErrorType.INTERNAL_ERROR,
            message    = str(e)
        )
        return Err(e)

async def main_req_rep(config:Config):
    global endpoint_manager
    logger.debug(f"Server - Listen on {config.AXO_PROTOCOL}://{AXO_REQ_RES_URI}")

    while True:
        t1 = T.time()

        extract_msg_result = await extract_task_envolope(socket=req_rep_socket)
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
                response = await ping(socket=req_rep_socket,envolpe=envelope,task=task)
            elif op == AxoOperationType.PUT_METADATA:
                response = await put_metadata_op(
                    socket           = req_rep_socket,
                    task             = task,
                    # metadata         = envelope.get_metadatax(),
                    envelope         = envelope,
                    store            = store,
                    endpoint_manager = endpoint_manager,
                    heater           = heater,
                    summoner         = summoner,
                    config           =  config
                )

            elif op == AxoOperationType.METHOD_EXEC:
                response = await method_exec_op(
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
                response = await create_endpoint(
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

    task1 = asyncio.create_task(main_req_rep(config=config))
    await asyncio.gather(task1)

if __name__ == "__main__":

    loop = asyncio.get_event_loop()
    # asyncio.set_event_loop(loop=loop)
    loop.run_until_complete(main())
