import os
import zmq
import time as T
import json as J
import string
import cloudpickle as CP
from option import Result,Ok,Err,Some,NONE
from typing import Any,Dict,List
from nanoid import generate as nanoid 

import axo_endpoint.utils as U
from axo_endpoint.interfaces import Heater,Task
from axo_endpoint.store import KVStore
from axo_endpoint.serde import Serde
import axo_endpoint.constants as CONSTANTS
from axo.log import get_logger
from axo.errors import AxoError,AxoErrorType
from axo.models import AxoRequestEnvelope
# 
from mictlanx import AsyncClient as MictlanXClient
from mictlanx.logger.log import Log
from axo_endpoint.endpoints import EndpointManager
from dataclasses import asdict
import json as J
# from axo_endpoint.endpoints import E
ALPHABET = string.ascii_lowercase+string.digits

AXO_ENDPOINT_IMAGE  = os.environ.get("AXO_ENDPOINT_IMAGE","nachocode/activex:endpoint")
AXO_ENDPOINT_ID     = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-0")
AXO_LOGGER_PATH     = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_LOGGER_WHEN     = os.environ.get("AXO_LOGGER_WHEN","h")
AXO_LOGGER_INTERVAL = int(os.environ.get("AXO_LOGGER_INTERVAL","24"))
AXO_SINK_PATH                 = os.environ.get("AXO_SINK_PATH","/sink")
AXO_SOURCE_PATH               = os.environ.get("AXO_SOURCE_PATH","/source")
AXO_DEBUG = bool(int(os.environ.get("AXO_DEBUG","1")))
logger = Log(
    console_handler_filter=lambda x: AXO_DEBUG,
    error_log=True,
    name="activex.method_exeution",
    path=AXO_LOGGER_PATH,
    when=AXO_LOGGER_WHEN,
    interval=AXO_LOGGER_INTERVAL,
)

async def elasticity(
        heater:Heater,
        serde:Serde,
        storage_service:MictlanXClient,
        store:KVStore,
        socket:zmq.Socket,
        task:Task,
        envelope:AxoRequestEnvelope,
        endpoint_manager:EndpointManager
        # summoner:Summoner 
)->Result[bool, AxoError]:
    try:
        rf = int(task.metadata.get("rf",1))
        created_endpoints_result = endpoint_manager.deploy_endpoint_bulk(rf=rf)
        
        if created_endpoints_result.is_err:
            _e = created_endpoints_result.unwrap_err()
            e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR,msg = str(_e))
            _ = await U.send_error_axo(socket=socket,operation=envelope.operation,task_id=envelope.task_id,msg_id=envelope.msg_id,error=e)
            return Err(e)
        
        created_endpoints = created_endpoints_result.unwrap()

        endpoints = list(map(lambda e: asdict(e), created_endpoints))
        _ = await U.send_ok(socket=socket,operation=envelope.operation,task_id=envelope.task_id,msg_id=envelope.msg_id)
        return Ok(True)
    except Exception as e:
        _e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR,msg = str(e))
        _ = await U.send_error_axo(socket=socket,operation=envelope.operation,task_id=envelope.task_id,msg_id=envelope.msg_id,error=_e)
        return Err(_e)
        
