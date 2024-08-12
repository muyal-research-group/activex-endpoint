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
from activexendpoint.utils import install_packages
from activex.endpoint import XoloEndpointManager
from activexendpoint.store import KVStore
from activexendpoint.controllers import put_metadata
from activexendpoint.serde import Serde
import activexendpoint.constants as CONSTANTS
# 
from mictlanx.v4.client import Client as MictlanXClient
from mictlanx.v4.interfaces import GetMetadataResponse,GetBytesResponse,Metadata
from mictlanx.logger.log import Log
from activex.storage.data import StorageService
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
async def manager_worker(
        endpoint_manager:XoloEndpointManager,
        heater:Heater,
        serde:Serde,
        storage_service:MictlanXClient,
        store:KVStore,
        req_rep_socket:zmq.Socket,
        task:Task
):
    axo_key          = task.get_axo_key()
    axo_bucket_id    = task.get_axo_bucket_id()
    source_bucket_id = task.get_source_bucket_id()
    sink_bucket_id   = task.get_sink_bucket_id()
    try:
        print("MANAGER WORKER EXECUTED")
        print(task.metadata)
        get_metadata_result:Result[GetMetadataResponse, Exception]= storage_service.get_metadata(
            key       = axo_key,
            bucket_id = axo_bucket_id
        )
        if get_metadata_result.is_err:
            error_msg = "{} not found".format(axo_key)
            logger.error({
                "event":"GET.METADATA.FAILED",
                "error":error_msg,
                "axo_bucket_id":axo_bucket_id,
                "key":axo_key
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
        metadata = get_metadata_result.unwrap().metadata
        print("METADATRa",metadata)
        obj_result_get_response :Result[GetBytesResponse,Exception]= storage_service.get_with_retry(
                bucket_id=axo_bucket_id,
                key=axo_key
        )

        # _______________________________________________________________________________________
        if obj_result_get_response.is_err:
            error_msg = "get_to_file failed"
            logger.error({
                "msg":error_msg, 
                "bucket_id":axo_bucket_id,
                "key":axo_key
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
        # _______________________________________________________________________________________
        get_obj_response = obj_result_get_response.unwrap()
        obj_bytes        = get_obj_response.value
        # _______________________________________________________________________________________
        obj_resul              =serde.deserialize_ao(obj_bytes)
        if obj_resul.is_err:
            error_msg = "DESERIALIZED.FAILED"
            logger.error({
                "event":error_msg,
                "bucket_id":axo_bucket_id,
                "key":axo_key,
                "msg":str(obj_resul.unwrap_err())
            })
            await req_rep_socket.send_multipart([b"activex",b"method.exec.failed",CONSTANTS.ERROR_STATUS,b"{}",b""])
            return Err(Exception(error_msg))
        axo_obj = obj_resul.unwrap()
        try: 
            source_keys = getattr(axo_obj,"source_keys")
            source_bucket_id = getattr(axo_obj,"source")
            sink_bucket_id = getattr(axo_obj,"sink")
            for source_key in source_keys:
                print("GET",source_bucket_id,source_key)
            # print("METHOD_CALL_RESULT", method_call_result)
            print("PUT RESULT IN",sink_bucket_id)
            print("F", task.f)
            # print("SOURCE_KEYUS", x)
        except Exception as e:
            print("ERROR SOURCE_KEUYS",e)
        # print("AXO_OBJ SOURCE_BUCKET_ID",axo_obj.source_bucket_id)
        # print("AXO_OBJ SOURCE_KEYS",axo_obj.source_keys)

        print("*"*50)
        await req_rep_socket.send_multipart([b"activex",b"success",CONSTANTS.SUCCESS_STATUS,b"{}",b""])
        return Ok(True)
    except Exception as e:
        return Err(e)