import os
import zmq
import time as T
import string
import types
import cloudpickle as CP
import inspect

from option import Result,Ok,Err,Some,NONE
from typing import Any,Dict,List
from nanoid import generate as nanoid 

from axo import Axo
from axo.errors import AxoError,AxoErrorType
from axo.models import AxoRequestEnvelope,MetadataX
from axo.log import get_logger
from axo.helpers import _generate_id
from axo.enums import AxoOperationType
from axo.storage.services import MictlanXStorageService
# 
from axo_endpoint.config import Config
import axo_endpoint.utils as U
from axo_endpoint.interfaces import Heater,Task
from axo_endpoint.utils import install_packages
from axo.endpoint.manager import DistributedEndpointManager
from axo_endpoint.store import KVStore
from axo_endpoint.store.models import MetadataKey
from axo_endpoint.serde import Serde
import axo_endpoint.constants as CONSTANTS
# 
from mictlanx import AsyncClient as MictlanXClient
from mictlanx.services import Summoner
import mictlanx.interfaces as InterfaceX
from functools import wraps
import asyncio

AXO_ENDPOINT_IMAGE = os.environ.get("AXO_ENDPOINT_IMAGE","nachocode/activex:endpoint")
AXO_ENDPOINT_ID    = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-0")
AXO_LOGGER_PATH    = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_SINK_PATH      = os.environ.get("AXO_SINK_PATH","/sink")


logger = get_logger(name=__name__,path=AXO_LOGGER_PATH,ltype="JSON")

async def stream_exec(
        endpoint_manager:DistributedEndpointManager,
        summoner:Summoner,
        heater:Heater,
        serde:Serde,
        storage_service:MictlanXClient,
        store:KVStore,
        req_rep_socket:zmq.Socket,
        task:Task,
        envelope: AxoRequestEnvelope,
        config:Config,
)->Result[Any,AxoError]:
    pass