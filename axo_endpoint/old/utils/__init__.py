
import sys
import string
from typing import Generator,Any,List,Dict,Tuple,Optional
import json as J
import time as T
import os
import subprocess
# 

from option import Result,Ok,Err,Some,NONE
import humanfriendly as HF
import cloudpickle as CP
from pydantic import ValidationError
from nanoid import generate as nanoid
import zmq.asyncio
# 
from mictlanx.services.models.summoner import SummonContainerPayload,ExposedPort,MountX
from mictlanx.services import Summoner
from mictlanx import AsyncClient as MictlanXClient
import mictlanx.interfaces as InterfaceX
# 
from axo_endpoint.interfaces import Task
from axo_endpoint.config import Config
#
from axo.models import AxoRequestEnvelope
from axo.log import get_logger
from axo.core.constants import *
from axo.models import AxoReplyEnvelope,MetadataX
from axo.core.models import AxoContext,DeserializeT,AckT
from axo.enums import AxoOperationType
from axo.errors import AxoError, AxoErrorType
from axo.endpoint.endpoint import DistributedEndpoint
from axo_endpoint.store.models import MetadataKey
from axo_endpoint.store import KVStore
import zmq
import types
from axo import Axo
import inspect
from functools import wraps
import asyncio
import wrapt


AXO_ENDPOINT_ID   = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-{}".format(nanoid(alphabet=string.ascii_lowercase+string.digits, size=8 )))
AXO_SUMMONER_MODE = os.environ.get("AXO_SUMMONER_MODE","docker")
AXO_LOGGER_PATH   = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_DEBUG         = bool(int(os.environ.get("AXO_DEBUG","1")))
logger            = get_logger(name=__name__,ltype="JSON",path=AXO_LOGGER_PATH,debug=AXO_DEBUG)


def validate_or_create_bucket_id(bucket_id:str):
    if bucket_id is None or bucket_id.strip() == "":
        return "axo_bucket_{}".format(nanoid(alphabet=string.ascii_lowercase+string.digits, size=8 ))
    return bucket_id

async def get_ao(
        store: KVStore,
        storage_client: MictlanXClient,
        axo_bucket_id:str,
        axo_key:str, 
        axo_alias:str,
        axo_version:int,
)->Result[Tuple[Axo,str,Dict[str,Any]],AxoError]:
    try: 
        _key           = MetadataKey(id = axo_key,version=axo_version,alias=axo_alias)
        maybe_metadata = store.get(key=_key)
        logger.debug({
            "axo_key":axo_key,
            "axo_version":axo_version,
            "axo_alias":axo_alias,
            "maybe_metadata":maybe_metadata.is_some
        })

        if maybe_metadata.is_none:
            logger.warning({
                "event":"LOCAL.NOT.FOUND",
                "axo_bucket_id":axo_bucket_id,
                "key":axo_key,
            })
            get_metadata_start_time = T.time()
            get_metadata_result:Result[InterfaceX.Ball,Exception] = await storage_client.get_metadata(
                bucket_id     = axo_bucket_id,
                ball_id       = f"{axo_key}_source_code",
            )



            # Check if get_metadata got an error_____________________________________________
            if get_metadata_result.is_err:
                get_metadata_result:Result[InterfaceX.Ball,Exception] = await storage_client.get_metadata(
                    bucket_id     = axo_bucket_id,
                    ball_id       = f"{axo_key}_source_code_0",
                )
                print("SECOND_CHECK",get_metadata_result)
                if get_metadata_result.is_err:
                    error_msg = f"Metadata not found: {axo_key}"
                    e         = AxoError.make(error_type=AxoErrorType.STORAGE_ERROR, msg= error_msg)
                    return Err(e)
            # _______________________________________________________________________________________

            remote_metadata = get_metadata_result.unwrap()
            logger.info({
                "event":"GET.REMOTE.METADATA",
                "bucket_id":axo_bucket_id,
                "key":axo_key,
                "response_time":T.time() - get_metadata_start_time
            })
            # remote_metadata.tags
            # await put_metadata()
            local_tags = remote_metadata.chunks[0].tags
            print("LOCAL_TAGS",local_tags)
            store.put(key=_key, value=local_tags )
            maybe_metadata = Some(MetadataX.model_validate(local_tags))



        local_metadata            = maybe_metadata.unwrap()
        mictlanx_get_start_time   = T.time()
        attrs_result_get_response = await storage_client.get(bucket_id=axo_bucket_id, key=f"{axo_key}_attrs")
        obj_result_get_response   = await storage_client.get(
            bucket_id=axo_bucket_id,
            key=f"{axo_key}_source_code"
        )

        if obj_result_get_response.is_err:
            e  = AxoError.make(error_type=AxoErrorType.STORAGE_ERROR, msg= "Get source code failed")
            return Err(e)


        if attrs_result_get_response.is_err:
            e  = AxoError.make(error_type=AxoErrorType.STORAGE_ERROR, msg= "Get attributes failed")
            return Err(e)
        get_obj_response           = obj_result_get_response.unwrap()
        source_code                = get_obj_response.data.tobytes().decode("utf-8")
        attrs_response             = attrs_result_get_response.unwrap()
        attrs                      = CP.loads(attrs_response.data.tobytes())
        mod                        = types.ModuleType("__axo_dynamic__")
        mod.__dict__["Axo"]        = Axo
        # This is provisional
        def axo_task(
            source_bucket: Optional[str] = "",
            sink_bucket: Optional[str] = "",
            filter_tags: Optional[Dict[str, str]] = None,
            filter_prefix: Optional[str] = None,
            deserialize: DeserializeT = "bytes",
            ack: AckT = "delete",
            lease_seconds: int = 60,
        ):
            # print("SORUCE",source_bucket)
            ctx = AxoContext(
                kind          = "task",
                source_bucket = source_bucket,
                sink_bucket   = sink_bucket,
                filter_tags   = filter_tags,
                filter_prefix = filter_prefix,
                deserialize   = deserialize,
                ack           = ack,
                lease_seconds = lease_seconds,
            )
            def decorator(fn):
                def __axo_task(_wrapped,ctx):
                    @wrapt.decorator
                    async def _wrapper(wrapped_func, instance,*args,**kwargs):
                        is_async = inspect.iscoroutinefunction(wrapped_func)
                        print("IS_ASYNC",is_async)
                        return Ok(None)
                        # logger.debug({
                        #     "event": "__AXO.TASK",
                        #     "fname": wrapped_func.__name__,
                        #     "args": ", ".join(map(repr, args)),
                        #     **{k: repr(v) for k, v in kwargs.items()}
                        # })
                        # if is_async:
                        #     result = await wrapped_func(*args, **kwargs)
                        # else:
                        #     # run sync function off the event loop
                        #     result = await asyncio.to_thread(wrapped_func, *args, **kwargs)

                        # print("_______RESULT", result)
                        # return Ok(result)
                    return _wrapper(_wrapped)
                return __axo_task(fn,ctx)


            return decorator
        # def axo_t(*args,**kwargs):
            # print("X",args)
            # return None
        mod.__dict__["axo_task"] = axo_task
        # mod.__dict__["axo_method"] = __axo_method
        class_name                 = get_obj_response.metadatas[0].tags.get("axo_class_name")
        exec(source_code, mod.__dict__)
        X = getattr(mod,class_name)
        obj = X(**attrs)
        for attr_name, attr_value in attrs.items():
            setattr(obj, attr_name, attr_value) 
        return Ok((obj,source_code,attrs))
    except Exception as e:
        return Err(AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR, msg= str(e)))

async def extract_task_envolope(socket:zmq.asyncio.Socket, )->Result[Tuple[Task,AxoRequestEnvelope,List[bytes]],AxoError]:
    
    try:
        multipart = await socket.recv_multipart()
        _start_time = T.time()
        # Parse task
        msg_result = from_multipart_to_task_and_envelope(multipart=multipart)
        if msg_result.is_err:
            e = msg_result.unwrap_err()
            await send_error_axo(
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
            "envelope":{**envelope.model_dump()},
            "task":{**task.to_dict()},
            "service_time":T.time()-_start_time
        })
        return Ok((task,envelope,frames))
    except Exception as e:
        await send_error(
            socket     = socket,
            operation  = AxoOperationType.UNKNOWN,
            task_id    = None,
            error_type = AxoErrorType.INTERNAL_ERROR,
            message    = str(e)
        )
        return Err(e)


async def send_axo_reply(
    socket: zmq.asyncio.Socket,
    *,
    operation: str,          # e.g. "PONG", "PUT.METADATA.REPLY", "METHOD.EXEC.REPLY"
    status: str,             # "ok" | "error"
    status_code:int,
    task_id: Optional[str],  # request envelope msg_id (if you have it)
    msg_id:str = None,
    envelope_overrides: Optional[dict] = None,
    payload_frames: Optional[List[bytes]] = None
)->Result[bool,AxoError]:
    """Send a protocol-correct Axo reply with optional payload frames."""
    try: 
        env = AxoReplyEnvelope(
            msg_id=msg_id,
            operation=operation,
            status=status,
            status_code= status_code,
            task_id=task_id,
            **(envelope_overrides or {}),
        )
        frames = [
            MAGIC,
            PROTO,
            operation.encode("utf-8"),
            JSON_CT,
            env.model_dump_json().encode("utf-8"),
        ]
        if payload_frames:
            frames.extend(payload_frames)
        # if 
        logger.debug(msg={**env.__dict__})
        await socket.send_multipart(frames)
        return Ok(True)
    except Exception as e:
        _e = AxoError.make(error_type=AxoErrorType.TRANSPORT_ERROR,msg=str(e))
        return Err(_e)


# --------------------------------------------------------------------
# Éxito (OK)
# --------------------------------------------------------------------
async def send_ok(
    socket: zmq.asyncio.Socket,
    *,
    operation: str,                     # p.ej. "PONG", "PUT.METADATA.REPLY"
    task_id: Optional[str]=None,
    msg_id:Optional[str]= None,
    envelope_overrides: Optional[Dict[str, Any]] = None,
    payload_frames: Optional[List[bytes]] = None,
) -> None:
    """
    Envia una respuesta de éxito usando el protocolo Axo.
    Equivalente moderno de 'send_success'.
    """
    await send_axo_reply(
        socket=socket,
        operation=operation,
        status="OK",
        status_code=0,
        task_id=task_id,
        msg_id=msg_id,
        envelope_overrides=envelope_overrides,
        payload_frames=payload_frames,
    )


# --------------------------------------------------------------------
# Error (ERROR) — recibe AxoError tipado
# --------------------------------------------------------------------
async def send_error_axo(
    socket: zmq.asyncio.Socket,
    *,
    operation: str,                     # p.ej. "REQUEST.FAILED", "METHOD.EXEC.REPLY"
    task_id: Optional[str],
    msg_id:Optional[str]= None,
    error: "AxoError",                  # modelo tipado
    envelope_overrides: Optional[Dict[str, Any]] = None,
    payload_frames: Optional[List[bytes]] = None,
) -> Result[bool, AxoError]:
    """
    Envia una respuesta de error usando un AxoError tipado.
    Equivalente moderno de 'send_error' pero con semántica fuerte.
    """
    # Fusiona overrides con el error serializado
    overrides = dict(envelope_overrides or {})
    overrides["error"] = error.model_dump()

    return await send_axo_reply(
        socket=socket,
        operation=operation,
        status="ERROR",
        status_code=error.code,     # usa el código del error
        task_id=task_id,
        msg_id=msg_id,
        envelope_overrides=overrides,
        payload_frames=payload_frames,
    )


# --------------------------------------------------------------------
# Error (ERROR) — atajo cuando no tienes AxoError y sólo un mensaje
# --------------------------------------------------------------------
async def send_error(
    socket: zmq.asyncio.Socket,
    *,
    operation: str,
    task_id: Optional[str],
    message: str,
    msg_id: Optional[str]=None,
    error_type: "AxoErrorType" = None,  # opcional: tipifica el error
    context: Optional[Dict[str, Any]] = None,
    suggestion: Optional[str] = None,
    retry_after_ms: Optional[int] = None,
    envelope_overrides: Optional[Dict[str, Any]] = None,
    payload_frames: Optional[List[bytes]] = None,
):
    """
    Azúcar sintáctico: construye un AxoError 'al vuelo' a partir de un mensaje.
    Útil en puntos de falla genéricos (parsing, excepciones inesperadas, etc).
    """
    et = error_type or AxoErrorType.INTERNAL_ERROR
    ax_err = AxoError.make(
        et,
        msg=message,
        context=context,
        suggestion=suggestion,
        retry_after_ms=retry_after_ms,
    )

    # logger.error({
    #    **ax_err.__dict__
    # })

    return await send_error_axo(
        socket=socket,
        operation=operation,
        task_id=task_id,
        msg_id=msg_id,
        error=ax_err,
        envelope_overrides=envelope_overrides,
        payload_frames=payload_frames,
    )




# ---------- Parser (new protocol) ----------
def from_multipart_to_task_and_envelope(
    multipart: List[bytes]
) -> Result[Tuple[Task, AxoRequestEnvelope, List[bytes]], AxoError]:
    """
    Parse NEW Axo protocol request:

    Frames:
      0: b"axo"
      1: b"v1"
      2: operation (bytes)
      3: b"application/json"
      4: envelope_json
      5+: payload (per operation)
    Returns:
      Ok((task, envelope_model, payload_frames))  |  Err(Exception)
    """
    try:
        if len(multipart) < 5:
            return Err(
                AxoError.make(
                    error_type = AxoErrorType.BAD_REQUEST,
                    msg        = f"Malformed multipart: expected > 5 frames, got {len(multipart)}"
                )
            )

        magic, version, op_b, ctype, env_b, *payload = multipart

        if magic != MAGIC:
            return Err(AxoError.make(msg = f"Invalid magic: {magic!r}", error_type=AxoErrorType.BAD_REQUEST))
        if version != PROTO:
            return Err(AxoError.make(msg=f"Unsupported protocol version: {version!r}", error_type=AxoErrorType.BAD_REQUEST))
        if ctype != JSON_CT:
            return Err(AxoError.make(msg=f"Unsupported content-type: {ctype!r}", error_type=AxoErrorType.BAD_REQUEST))

        operation = op_b.decode("utf-8", errors="replace").strip().upper()

        # Parse envelope with Pydantic
        try:
            env_dict = J.loads(env_b)
            envelope = AxoRequestEnvelope.model_validate({**env_dict, "operation": operation})
        except (J.JSONDecodeError, ValidationError) as e:
            return Err(AxoError.make(msg= f"Invalid envelope: {e}", error_type=AxoErrorType.BAD_REQUEST))

        # Build Task.metadata as dict to preserve your current helpers
        metadata: Dict[str, Any] = envelope.model_dump()

        # METHOD.EXEC requires exactly 2 payload frames: fargs, fkwargs
        if operation == AxoOperationType.METHOD_EXEC:
            if len(payload) != 2:
                return Err(
                    AxoError.make(
                        msg        = f"METHOD.EXEC expected 2 payload frames (fargs, fkwargs), got {len(payload)}",
                        error_type = AxoErrorType.BAD_REQUEST
                    )
                )
            try:
                fargs = CP.loads(payload[0])
                fkwargs = CP.loads(payload[1])
            except Exception as e:
                return Err(AxoError.make(msg= f"Failed to deserialize METHOD.EXEC args/kwargs: {e}", error_type=AxoErrorType.BAD_REQUEST))

            task = Task(
                namespace = "axo",
                operation = operation,
                metadata  = metadata,
                fargs     = fargs,
                fkwargs   = fkwargs,
            )
            print("METADDA", metadata)
            print(task,task.__dict__)
            envelope.task_id = task.task_id
            return Ok((task, envelope, payload))

        elif operation == AxoOperationType.TASK_EXEC:
            if len(payload) != 3:
                return Err(
                    AxoError.make(
                        msg        = f"METHOD.EXEC expected 3 payload frames (fargs, fkwargs,ctx), got {len(payload)}",
                        error_type = AxoErrorType.BAD_REQUEST
                    )
                )
            try:
                fargs = CP.loads(payload[0])
                fkwargs = CP.loads(payload[1])
                ctx = CP.loads(payload[2])
            except Exception as e:
                return Err(AxoError.make(msg= f"Failed to deserialize TASK.EXEC args/kwargs: {e}", error_type=AxoErrorType.BAD_REQUEST))

            task = Task(
                namespace="axo",
                operation=operation,
                metadata=metadata,
                fargs=fargs,
                fkwargs=fkwargs,
                ctx=ctx
            )
            envelope.task_id = task.task_id
            return Ok((task, envelope, payload))

        # PUT.METADATA / others: just pass envelope as metadata
        task = Task(namespace="axo", operation=operation, metadata=metadata)
        # print("METADATA",metadata)
        # print("TASK",task.__dict__)
        # print("ENVELOPE",envelope.__dict__)
        return Ok((task, envelope, payload))

    except Exception as e:
        return Err(AxoError.make(msg = str(e), error_type=AxoErrorType.INTERNAL_ERROR))



def dict_any_to_dict_str(xs:Dict[str,Any]):
    return (dict(list(map(lambda x: (x[0],str(x[1])),xs.items()))))

        # print("h3",attrs)

def byte_generator(data, chunk_size=1024)->Generator[bytes,Any,Any]:
    """
    Generator that yields chunks of data.
    
    Args:
    - data: The data to be chunked.
    - chunk_size: The size of each chunk in bytes.
    
    Yields:
    - Chunks of data of the specified chunk size.
    """
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]


def install_package(package:str)->Result[int,Exception]:
    try:
        # status = subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        # status = subprocess.check_call([sys.executable, "-m", "poetry", "add", package])
        start_time = T.time()
        logger.debug({
            "event":"DEPENDENCY.INSTALLATION.START",
            "dependency":package
        })
        command = "poetry add {}".format(package)
        status = subprocess.run(command, shell=True, capture_output=True, text=True)
        logger.info({
            "event":"DEPENDENCY.INSTALLED",
            "executable":sys.executable,
            "stdout":status.stdout,
            "stderr":status.stderr,
            "dependencie": package,
            "response_time":T.time() - start_time
        })
        return Ok(0)
    except Exception as e:
        logger.error({
            "event":"DEPENDENCY.INSTALLATION.FAILED",
            "dependencie": package,
            "error":str(e),
            "x":e.with_traceback()
        })
        return Err(e)

def install_packages(packages:List[str]=0)->Result[int, Exception]:
    
    try:
        start_time = T.time()
        succ=0
        for package in packages:
            res = install_package(package=package)
            if res.is_ok:
                succ+=1
        logger.info({
            "event":"DEPENDENCY.INSTALLATION.COMPLETED",
            "total_dependencies":len(packages),
            "installed_dependencies":succ,
            "failed_dependencies":len(packages) - succ,
            "response_time":T.time() - start_time
        })
        return Ok(0)
    except Exception as e:
        logger.error(str(e))
        return Err(e)

def deploy_endpoint(
        summoner:Summoner,
        endpoint_id:str,
        config:Config,
        endpoints:List[str]=[],
        cpu_count:int=2,
        memory:str="1GB",
        selected_node:str="0",
        dependencies:List[str]=[],
        pubsub_port:int=16666,
        req_res_port:int=16667,
        hostname:str="*",
        image:str= "nachocode/axo:endpoint-0.0.3a0"
):
    start_time = T.time()
    try:
        envs = {
                # AXO core
                "AXO_ENDPOINT_ID": endpoint_id,
                "AXO_ENDPOINT_DEPENDENCIES": ";".join(dependencies),
                "AXO_LOGGER_PATH": config.AXO_LOGGER_PATH,
                "AXO_LOGGER_WHEN": config.AXO_LOGGER_WHEN,
                "AXO_LOGGER_INTERVAL": config.AXO_LOGGER_INTERVAL,
                "AXO_SYNC_MAX_IDLE_TIME": config.AXO_SYNC_MAX_IDLE_TIME,
                "AXO_HEATER_TICK_TIME": config.AXO_HEATER_TICK_TIME,
                "AXO_SINK_PATH": config.AXO_SINK_PATH,
                "AXO_SOURCE_PATH": config.AXO_SOURCE_PATH,
                "AXO_DATA_PATH": config.AXO_DATA_PATH,
                "AXO_ENDPOINT_IMAGE": image,
                "AXO_PROTOCOL": config.AXO_PROTOCOL,
                "AXO_PUB_SUB_PORT": str(pubsub_port),
                "AXO_REQ_RES_PORT": str(req_res_port),
                "AXO_HOSTNAME": hostname,
                "AXO_SUBSCRIBER_HOSTNAME": config.AXO_SUBSCRIBER_HOSTNAME,
                "AXO_ENDPOINTS": " ".join(endpoints),
                "AXO_HEATER_MAX_IDLE_TIME": config.AXO_HEATER_MAX_IDLE_TIME,
                "AXO_DEBUG": int(config.AXO_DEBUG),  # default true
                "AXO_METADATA_TIMEOUT": config.AXO_METADATA_TIMEOUT,

                # MictlanX Summoner
                "MICTLANX_SUMMONER_IP_ADDR": config.MICTLANX_SUMMONER_IP_ADDR,
                "MICTLANX_SUMMONER_API_VERSION": config.MICTLANX_SUMMONER_API_VERSION,
                "MICTLANX_SUMMONER_NETWORK": config.MICTLANX_SUMMONER_NETWORK,
                "MICTLANX_SUMMONER_PORT": config.MICTLANX_SUMMONER_PORT,
                "MICTLANX_SUMMONER_PROTOCOL": config.MICTLANX_SUMMONER_PROTOCOL,
                "MICTLANX_SUMMONER_MODE": config.MICTLANX_SUMMONER_MODE,

                # MictlanX client / bucket / routers
                "MICTLANX_BUCKET_ID": config.MICTLANX_BUCKET_ID,
                "MICTLANX_ROUTERS": config.MICTLANX_URI,
                "MICTLANX_CLIENT_ID": endpoint_id,
                "MICTLANX_DEBUG": int(config.MICTLANX_DEBUG),
                "MICTLANX_LOG_INTERVAL": config.MICTLANX_LOG_INTERVAL,
                "MICTLANX_LOG_WHEN": config.MICTLANX_LOG_WHEN,
                "MICTLANX_LOG_OUTPUT_PATH": config.MICTLANX_LOG_OUTPUT_PATH,
                "MICTLANX_MAX_WORKERS": config.MICTLANX_MAX_WORKERS,

                # Aliases
                "NODE_IP_ADDR": endpoint_id,
                "NODE_PORT": str(req_res_port),
        }
        envs = dict(map(lambda x: (x[0],str(x[1]) ), envs.items()))
        payload = SummonContainerPayload(
            container_id  = endpoint_id,
            image         = image,
            cpu_count     = cpu_count,
            envs          = envs,
            exposed_ports = [
                ExposedPort(host_port=pubsub_port,container_port=pubsub_port,ip_addr=None, protocol=None),
                ExposedPort(host_port=req_res_port,container_port=req_res_port,ip_addr=None, protocol=None),
            ],
            force    = True,
            hostname = endpoint_id,
            ip_addr  = endpoint_id,
            labels   = {
                "axo"     : "",
                "axo.type": "endpoint"
            },
            memory   = HF.parse_size(memory),
            mounts   = [
                MountX(
                    source     = f"{endpoint_id}-log",
                    target     = "/log",
                    mount_type = 1,
                ),
                MountX(
                    source     = f"{endpoint_id}-data",
                    target     = "/data",
                    mount_type = 1,
                ),
            ],
            network_id    = config.AXO_NETWORK_ID,
            selected_node = selected_node,
            shm_size      = None,
        )
        # logger.info({
        #     "envet":"DEPLOY.ENDPOINT",
        #     "endpoint_id":endpoint_id,
        #     "req_res_port":req_res_port,
        #     "pubsub_port":pubsub_port,
        #     "response_time":T.time()-start_time
        # })
        return summoner.summon(
            payload= payload,
            mode=AXO_SUMMONER_MODE
        )
    except Exception as e:
        logger.error({
            "error":str(e),
            "endpoint_id":endpoint_id,
            "req_res_port":req_res_port,
            "pubsub_port":pubsub_port
        })


async def __deploy_endpoint(
        summoner:Summoner,
        endpoint_id:str,
        req_res_port:int, 
        pubsub_port:int,
        config:Config,
        dependencies:List[str]=[],
        image:str = "nachocode/axo:endpoint-0.0.1a4"
)->Result[DistributedEndpoint,AxoError]:
    try:
        deploy_endpoint_start_time = T.time()
        logger.debug({
            "event":"DEPLOY.ENDPOINT",
            "endpoint_id":endpoint_id,
            "pubsub_port":pubsub_port,
            "req_res_port":req_res_port
        })
        endpoint_deploy_result = deploy_endpoint(
            summoner     = summoner,
            config       = config,
            endpoint_id  = endpoint_id,
            pubsub_port  = pubsub_port,
            req_res_port = req_res_port,
            dependencies = dependencies,
            image        = image
        )
        if endpoint_deploy_result.is_ok:
            container_endpoint = endpoint_deploy_result.unwrap()
            logger.info({
                "event":"DEPLOY.ENDPOINT",
                "endpoint_id":endpoint_id,
                "req_res_port":req_res_port,
                "pubsub_port":pubsub_port,
                "container_id":container_endpoint.container_id,
                "response_time":T.time() - deploy_endpoint_start_time
            })
            return Ok(DistributedEndpoint(endpoint_id=endpoint_id, hostname=container_endpoint.ip_addr, req_res_port=req_res_port,pubsub_port=pubsub_port))
        
        else:
            _e    = endpoint_deploy_result.unwrap_err()
            axo_e = AxoError.make(error_type=AxoErrorType.ENDPOINT_DEPLOY_FAILED, msg=str(_e))
            logger.error({
                "error":"DEPLOY.ENDPOINT.FAILED",
                "msg":str(axo_e),
                "endpoint_id":endpoint_id,
                "req_res_port":req_res_port,
                "pubsub_port":pubsub_port
            })
            return Err(axo_e)
    except Exception as e:
        _e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR, msg=str(e))
        logger.error({
            "error":"INTERNAL.ERROR",
            "msg":str(_e),
            "endpoint_id":endpoint_id,
            "req_res_port":req_res_port,
            "pubsub_port":pubsub_port
        })
        return Err(_e)
