
import time as T
import asyncio
import zmq.asyncio 
from option import Some,Result,Ok,Err
# Axo
from axo.endpoint.manager import DistributedEndpointManager
from axo.models import AxoRequestEnvelope
from axo.enums import AxoOperationType
from axo.errors import AxoErrorType,AxoError
from axo.log import Log
# Mictlanx
from mictlanx import AsyncClient
from mictlanx.services import Summoner

# ActivexEndpoitn
from axo_endpoint.endpoints import EndpointManager
from axo_endpoint.controllers import put_metadata,method_exeution,elasticity,stream_exec,task_exec
import axo_endpoint.utils as U
from axo_endpoint.store import SimpleStore
from axo_endpoint.interfaces import Heater
from axo_endpoint.serde import DefaultSerde
from axo_endpoint.config import Config
from axo_endpoint.interfaces import Task


config            = Config()

logger = Log(
    console_handler_filter = lambda x: config.AXO_DEBUG,
    error_log              = True,
    name                   = config.AXO_ENDPOINT_ID,
    path                   = config.AXO_LOGGER_PATH,
    when                   = config.AXO_LOGGER_WHEN,
    interval               = config.AXO_LOGGER_INTERVAL,
)

async def ping(socket:zmq.asyncio.Socket,task:Task,envolpe:AxoRequestEnvelope,heater:Heater):
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
        # print("PUT METADATA OP",metadata)
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
            socket   = socket,           # kept for signature; do not use to send
            task             = task,
            envelope         = envelope,
            config           = config,
        )

        if exec_res.is_err:
            e = exec_res.unwrap_err()
            _ = await U.send_error_axo(socket=socket, operation=envelope.operation, task_id = envelope.task_id,msg_id=envelope.msg_id, error = e)
            return Err(exec_res.unwrap_err())


        logger.info({
            "event": "METHOD.EXEC.REPLY",
            "task_id": task.task_id,
            "object_id": envelope.axo_uri,
            "method": envelope.method,
            "axo_version": envelope.axo_version,
            "response_time": T.time() - t0,
        })
        return Ok(None)

    except Exception as e:
        _e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR,msg=str(e))
        await U.send_error_axo(socket=socket, operation=envelope.operation,task_id=envelope.task_id,msg_id = envelope.msg_id,error = _e)
        return Err(_e)


# ------------------------------------------------------------------------------
# TASK.EXEC
# ------------------------------------------------------------------------------
async def task_exec_op(
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
    t0 = T.time()
    endpoint_id = envelope.axo_endpoint_id
    exists      = endpoint_manager.exists(endpoint_id=endpoint_id)
    
    dependencies             = envelope.axo_dependencies
    deps_installation_result = U.install_packages(packages=dependencies)

    if deps_installation_result.is_err:
        logger.warning({
            "event":"DEPENDENCIES.INSTALLATION.FAILED",
            "error":str(deps_installation_result.unwrap_err())
        })

    if not exists:
        logger.warning({
            "event":"DEPLOY.ENDPOINT", 
            "endpoint_id":endpoint_id,
            "node_id":config.AXO_ENDPOINT_ID,
        })
        ud_endpoint_image = getattr(envelope,"axo_endpoint_image")
        # i = endpoint_manager.get
        deploy_endpoint_result = await U.__deploy_endpoint(
            summoner     = summoner,
            endpoint_id  = endpoint_id,
            req_res_port = endpoint_manager.get_available_req_res_port(),
            pubsub_port  = endpoint_manager.get_available_pubsub_port(),
            config       = config,
            dependencies = dependencies,
            image        =  ud_endpoint_image or config.AXO_ENDPOINT_IMAGE
        )
        if deploy_endpoint_result.is_err:
            e = deploy_endpoint_result.unwrap_err()
            _ = await U.send_error_axo(socket=socket, operation=envelope.operation, task_id = envelope.task_id,msg_id=envelope.msg_id, error = e)
            return Err(e)

            # return Err(chunk_ref.unwrap_err() ) 

    print("*"*40)
    print("BEFORE TASK_EXEC")
    exec_res = await task_exec(
        store            = store,
        socket           = socket,             # keep for signature; avoid sending inside
        serde            = serde,
        storage_client   = storage_service,
        endpoint_manager = endpoint_manager,
        heater           = heater,
        task             = task,
        envelope         = envelope,
        config           = config,
        summoner         = summoner,
    )
    if exec_res.is_err:
        e = exec_res.unwrap_err()
        _ = await U.send_error_axo(socket=socket, operation=envelope.operation, task_id = envelope.task_id,msg_id=envelope.msg_id, error = e)
        return Err(exec_res.unwrap_err())
    logger.info({
        "event": "TASK.EXEC.RESPONSE",
        "task_id": task.task_id,
        "uri": envelope.axo_uri,
        "method": envelope.method,
        "axo_version": envelope.axo_version,
        "ok":exec_res.is_ok,
        "response_time": T.time() - t0,
    })   

    return Ok(None)


async def stream_exec_op(
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
    res = stream_exec(
        store=store,
        socket=socket,        # keep for signature; avoid sending inside
        serde=serde,
        storage_service=storage_service,
        endpoint_manager=endpoint_manager,
        heater=heater,
        task=task,

    )
    return Ok(None)
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
            socket=socket,        # keep for signature; avoid sending inside
            serde=serde,
            storage_service=storage_service,
            endpoint_manager=endpoint_manager_x,
            heater=heater,
            task=task,
        )

        if res.is_err:
            err_msg = str(res.unwrap_err())
            # e = AxoError
            return Err(Exception(err_msg))

        # await U.send_ok(
        #     socket             = socket,
        #     operation          = AxoOperationType.CREATE_ENDPOINT,
        #     task_id            = task.task_id,
        #     envelope_overrides = {
        #         "axo_uri": envelope.axo_uri,
        #     },
        # )

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


