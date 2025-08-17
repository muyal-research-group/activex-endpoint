
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
from mictlanx.v4.summoner.summoner import Summoner ,SummonContainerPayload,ExposedPort
from mictlanx.interfaces.payloads import MountX
# 
from axo_endpoint.interfaces import Task
#
from axo.models import AxoRequestEnvelope
from axo.log import get_logger
from axo.core.constants import *
from axo.models import AxoReplyEnvelope
from axo.errors import AxoError, AxoErrorType

AXO_ENDPOINT_ID   = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-{}".format(nanoid(alphabet=string.ascii_lowercase+string.digits, size=8 )))
AXO_SUMMONER_MODE = os.environ.get("AXO_SUMMONER_MODE","docker")
AXO_LOGGER_PATH   = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_DEBUG         = bool(int(os.environ.get("AXO_DEBUG","1")))
logger            = get_logger(name=__name__,ltype="JSON",path=AXO_LOGGER_PATH,debug=AXO_DEBUG)

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
):
    """Send a protocol-correct Axo reply with optional payload frames."""
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
) -> None:
    """
    Envia una respuesta de error usando un AxoError tipado.
    Equivalente moderno de 'send_error' pero con semántica fuerte.
    """
    # Fusiona overrides con el error serializado
    overrides = dict(envelope_overrides or {})
    overrides["error"] = error.model_dump()

    await send_axo_reply(
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
) -> None:
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

    await send_error_axo(
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
                    msg        = f"Malformed multipart: expected ≥5 frames, got {len(multipart)}"
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
        if operation == "METHOD.EXEC":
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
                namespace="axo",
                operation=operation,
                metadata=metadata,
                fargs=fargs,
                fkwargs=fkwargs,
            )
            envelope.task_id = task.task_id
            return Ok((task, envelope, payload))

        # PUT.METADATA / others: just pass envelope as metadata
        task = Task(namespace="axo", operation=operation, metadata=metadata)
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
        cpu_count:int=2,
        memory:str="1GB",
        selected_node:str="0",
        dependencies:List[str]=[],
        pubsub_port:int=16666,
        req_res_port:int=16667,
        hostname:str="*",
        image:str= "nachocode/activex:endpoint"
):
    start_time = T.time()
    try:
        payload = SummonContainerPayload(
            container_id=endpoint_id, 
            image= image,
            cpu_count=cpu_count,
            envs={
                "AXO_ENDPOINT_ID": endpoint_id,
                "AXO_ENDPOINT_DEPENDENCIES": ";".join(dependencies),
                "AXO_LOGGER_PATH": "/log",
                "AXO_LOGGER_WHEN": "h",
                "AXO_LOGGER_INTERVAL": "24",
                "AXO_ENDPOINT_IMAGE": image,
                "AXO_PROTOCOL": "tcp",
                "AXO_PUB_SUB_PORT":str(pubsub_port),
                "AXO_REQ_RES_PORT": str(req_res_port),
                "AXO_HOSTNAME": hostname,
                "MICTLANX_XOLO_IP_ADDR": "mictlanx-xolo-0",
                "MICTLANX_XOLO_API_VERSION": "3",
                "MICTLANX_XOLO_NETWORK": "10.0.0.0/25",
                "MICTLANX_XOLO_PORT": "15000",
                "MICTLANX_XOLO_MODE":AXO_SUMMONER_MODE,
                "MICTLANX_XOLO_PROTOCOL": "http",
                "MICTLANX_CLIENT_ID":endpoint_id,
                "MICTLANX_BUCKET_ID": "activex",
                "MICTLANX_DEBUG": "0",
                "MICTLANX_LOG_INTERVAL": "24",
                "MICTLANX_LOG_WHEN": "h",
                "MICTLANX_LOG_OUTPUT_PATH": "/log",
                "MICTLANX_MAX_WORKERS": "4",
                "MICTLANX_ROUTERS": "mictlanx-router-0:mictlanx-router-0:60666",
                "NODE_IP_ADDR":endpoint_id,
                "NODE_PORT":str(req_res_port),
            },
            exposed_ports=[
                ExposedPort(host_port=pubsub_port,container_port=pubsub_port,ip_addr=NONE, protocolo=NONE),
                ExposedPort(host_port=req_res_port,container_port=req_res_port,ip_addr=NONE, protocolo=NONE),
            ],
            force=Some(True),
            hostname=endpoint_id,
            ip_addr=Some(endpoint_id),
            labels={
                "activex":"",
                "activex.type":"endpoint"
            },
            memory=HF.parse_size(memory),
            mounts=[
                MountX(
                    source=endpoint_id,
                    target="/log",
                    mount_type=1,
                ),
                MountX(
                    source=endpoint_id,
                    target="/data",
                    mount_type=1,
                ),
            ],
            network_id="mictlanx",
            selected_node=Some(selected_node),
            shm_size=NONE,
        )
        logger.info({
            "envet":"DEPLOY.ENDPOINT",
            "endpoint_id":endpoint_id,
            "req_res_port":req_res_port,
            "pubsub_port":pubsub_port,
            "response_time":T.time()-start_time
        })
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