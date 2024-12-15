import os
import zmq
import time as T
import json as J
import string
import cloudpickle as CP
from option import Result,Ok,Err,Some,NONE
from typing import Any,Dict,List
from nanoid import generate as nanoid 

from activex import Axo
import activexendpoint.utils as U
from activexendpoint.interfaces import Heater,Task
from activexendpoint.utils import install_packages,deploy_endpoint
from activex.endpoint import XoloEndpointManager
from activexendpoint.store import KVStore
from activexendpoint.controllers import put_metadata
from activexendpoint.serde import Serde
import activexendpoint.constants as CONSTANTS
# 
from mictlanx.v4.client import Client as MictlanXClient
from mictlanx.v4.summoner.summoner import Summoner,SummonContainerPayload
from mictlanx.v4.interfaces import GetMetadataResponse,GetBytesResponse,Metadata
from mictlanx.logger.log import Log
from activex.storage.data import StorageService
from activexendpoint.endpoints import EndpointManager
from dataclasses import asdict
import json as J
# from activexendpoint.endpoints import E
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
    create_folder=True,
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
        req_rep_socket:zmq.Socket,
        task:Task,
        endpoint_manager:EndpointManager
        # summoner:Summoner 
):
    try:
        rf = int(task.metadata.get("rf",1))
        endpoints = list(map(lambda e: asdict(e),endpoint_manager.deploy_endpoint_bulk(rf=rf)))
        await req_rep_socket.send_multipart([b"activex",b"success",CONSTANTS.SUCCESS_STATUS,b"{}",CP.dumps(endpoints)])
        return Ok(True)
    except Exception as e:
        await req_rep_socket.send_multipart([b"activex",b"error",CONSTANTS.ERROR_STATUS,b"{}",str(e).encode() ])
        return Err(e)
        
