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
from mictlanx.v4.asyncx import AsyncClient as MictlanXClient
from mictlanx.v4.summoner.summoner import Summoner
import mictlanx.v4.interfaces as InterfaceX
import mictlanx.v4.models as ModelX

AXO_ENDPOINT_IMAGE = os.environ.get("AXO_ENDPOINT_IMAGE","nachocode/activex:endpoint")
AXO_ENDPOINT_ID    = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-0")
AXO_LOGGER_PATH    = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_SINK_PATH      = os.environ.get("AXO_SINK_PATH","/sink")



logger = get_logger(name=__name__,path=AXO_LOGGER_PATH,ltype="JSON")

def __axo_method(f):
    def __inner(*args,**kwargs):
        try:
            logger.debug({
                "event":"__AXO_METHOD",
                "fname":f.__name__,
                "args":",".join(map(str,args)),
                **kwargs
            })
            result = f(*args,**kwargs)
            print("_______RESULT",result)
            return Ok(result)
        except Exception as e:
            logger.error({"event":"FAILED.__AXO_METHOD","detail":str(e)})
            return Err(e)
    return __inner


async def __call(
        obj:Any,
        fname:str,
        ball:InterfaceX.Metadata,
        serde:Serde,
        sink_bucket_id:str,
        axo_sink_path_sink_bucket_id_path:str,
        storage_service:MictlanXClient,
        task_fkwargs:Dict[str,Any] = {},
        task_fargs:List[Any] = ()
):
    axo_sink_key  = nanoid(alphabet=string.ascii_lowercase+string.digits,size=16)
    axo_sink_path = "{}/{}".format(axo_sink_path_sink_bucket_id_path,axo_sink_key)
    axo_result_id = "{}.{}.{}".format(fname,sink_bucket_id ,axo_sink_key )
    fkwargs = {
        **task_fkwargs,
        "axo_result_id":axo_result_id,
        "axo_sink_path_sink_bucket_id_path":axo_sink_path_sink_bucket_id_path,
        "axo_sink_path":axo_sink_path,
        "axo_sink_key":axo_sink_key,
        "source_bucket_id":ball.bucket_id,
        "source_key":ball.key,
        "method_name":fname,
        "metadata":ball.tags,
        "storage":storage_service
    }
    t_call_start = T.time()
    # method_call_result = Axo.call(*task.fargs,instance=obj,**fkwargs)
    method_call_result = Axo.call(*task_fargs,**{"instance":obj,**fkwargs})
    if method_call_result.is_ok:
        logger.info({
            "event":"METHOD.CALL",
            "method_name":fname,
            "axo_result_id":axo_result_id,
            "axo_sink_path":axo_sink_path,
            "axo_sink_key":axo_sink_key,
            "source_bucket_id":ball.bucket_id,
            "source_key":ball.key,
            "response_time":T.time() -  t_call_start
        })
        method_call_response = method_call_result.unwrap()
        if isinstance(method_call_response, Exception):
            logger.error({
                "event":"METHOD.CALL.FAILED",
                "msg":str(method_call_response)
            })
            return Err(method_call_response)
            
        # print("METHOD_CALL.RESPONSE", method_call_result)
        if not method_call_response == None:
            (f_serialize_mode,f_result_bytes)= serde.serialize_fresult(result=method_call_response).unwrap()
            axo_fsink_key = nanoid(alphabet=string.ascii_lowercase+string.digits, size=16)
            # result_json[axo_result_id] = f_result_bytes.decode() if f_serialize_mode == 0 else axo_fsink_key
            put_result   = storage_service.put_chunked(
                chunks=U.byte_generator(f_result_bytes),
                bucket_id=sink_bucket_id,
                key=axo_fsink_key,
                tags={
                    "method_name":fname,
                    "axo_result_id":axo_result_id,
                    "axo_sink_path":axo_sink_path,
                    "axo_sink_key":axo_sink_key,
                    "source_bucket_id":ball.bucket_id,
                    "source_key":ball.key,
                }
            )
            if put_result.is_err:
                return Err(put_result.unwrap_err())
                # fbs = result_json.setdefault("failed_balls",0)
                # result_json["failed_balls"] = fbs +1
                # logger.error({
                #     "event":"PUT.CHUNKED.FAILED",
                #     "bucket_id":axo_bucket_id,
                #     "key":axo_fsink_key,
                # })
            else:
                status = 1 
                return Ok(method_call_response)
                # fbs = result_json.setdefault("successed_balls",0)
                # result_json["successed_balls"] = fbs +1
        else:
            return Ok(None)
            # return Err(Exception("{} execution failed".format(fname)))
            # logger.warning({
            #     "event":"METHOD.EXEC.NO.OUTPUT",
            #     "axo_source_bucket_id":source_bucket_id,
            #     # "axo_source_path":source_ball_local_path,
            #     "axo_sink_bucket_id":sink_bucket_id,
            #     "axo_bucket_sink_path":axo_sink_path_source_bucket_id_path,
            #     "axo_sink_path":axo_sink_path,
            #     "axo_sink_key":axo_sink_key,
            #     "response_time": T.time()- start_time
            # })
            
            # raise 
    else:
        error = method_call_result.unwrap_err()
        logger.error({
            "event":"METHOD.EXCUTION.FAILED",
            "reason":str(error )
        })
        return Err(error)


async def __method_execution(
        serde:Serde,
        storage_service:MictlanXClient,
        store:KVStore,
        socket:zmq.Socket,
        task:Task,
        envelope:AxoRequestEnvelope,
)->Result[Any, AxoError]:
    start_time       = T.time()
    axo_key          = task.get_axo_key()
    axo_bucket_id    = task.get_axo_bucket_id()
    source_bucket_id = task.get_source_bucket_id()
    sink_bucket_id   = task.get_sink_bucket_id()
    axo_sink_path_source_bucket_id_path = "{}/{}".format(AXO_SINK_PATH,source_bucket_id)
    axo_sink_path_sink_bucket_id_path   = "{}/{}".format(AXO_SINK_PATH,sink_bucket_id)
    os.makedirs(axo_sink_path_sink_bucket_id_path,exist_ok=True)
    logger.debug({
        "axo_key":axo_key,
        "axo_bucket_id":axo_bucket_id,
        "axo_source_bucket_id":source_bucket_id,
        "axo_sink_bucket_id":sink_bucket_id
    })
    try:

        # _______________________________________________________________________________________
        _key = MetadataKey(id = envelope.axo_key,version=envelope.axo_version,alias=envelope.axo_alias)

        maybe_metadata = store.get(key=_key)
        if maybe_metadata.is_none:
            logger.warning({
                "event":"LOCAL.NOT.FOUND",
                "axo_bucket_id":axo_bucket_id,
                "key":axo_key,
            })
            get_metadata_start_time = T.time()
            get_metadata_result:Result[ModelX.Ball,Exception] = await storage_service.get_metadata(
                bucket_id     = axo_bucket_id,
                ball_id       = f"{axo_key}_source_code",
            )
            # Check if get_metadata got an error_____________________________________________
            if get_metadata_result.is_err:
                error_msg = f"Metadata not found: {axo_key}"
                e         = AxoError.make(error_type=AxoErrorType.STORAGE_ERROR, msg= error_msg)
                await U.send_error_axo(socket=socket, operation=envelope.operation, task_id = envelope.task_id,msg_id=envelope.msg_id, error = e)
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
            store.put(key=axo_key, value=local_tags )
            maybe_metadata = Some(MetadataX.model_validate(local_tags))
        
        local_metadata            = maybe_metadata.unwrap()
        mictlanx_get_start_time   = T.time()
        attrs_result_get_response = await storage_service.get(bucket_id=axo_bucket_id, key=f"{axo_key}_attrs")
        obj_result_get_response   = await storage_service.get(
            bucket_id=axo_bucket_id,
            key=f"{axo_key}_source_code"
        )

        if obj_result_get_response.is_err:
            e  = AxoError.make(error_type=AxoErrorType.STORAGE_ERROR, msg= "Get source code failed")
            return Err(e)

        
        if attrs_result_get_response.is_err:
            e  = AxoError.make(error_type=AxoErrorType.STORAGE_ERROR, msg= "Get attributes failed")
            return Err(e)

        # _______________________________________________________________________________________
        get_obj_response           = obj_result_get_response.unwrap()
        source_code                = get_obj_response.data.tobytes().decode("utf-8")
        attrs_response             = attrs_result_get_response.unwrap()
        attrs                      = CP.loads(attrs_response.data.tobytes())
        mod                        = types.ModuleType("__axo_dynamic__")
        mod.__dict__["Axo"]        = Axo
        # This is provisional
        mod.__dict__["axo_method"] = lambda x:x
        # mod.__dict__["axo_method"] = __axo_method
        class_name                 = get_obj_response.metadatas[0].tags.get("axo_class_name")
        exec(source_code, mod.__dict__)
        X = getattr(mod,class_name)
        obj = X(**attrs)
        # GET SOURCE BUCKET
        t1_get_source_bucket = T.time()
        # _______________________________________________________________________________________
        bucket_result = await storage_service.get_bucket_metadata(bucket_id=source_bucket_id)
        if bucket_result.is_err:
            error_msg = f"Get bucket failed: {source_bucket_id}"
            e         = AxoError.make(error_type=AxoErrorType.STORAGE_ERROR, msg= error_msg)
            return Err(e)
     
        bucket = bucket_result.unwrap()
        logger.info({
            "event":"GET.BUCKET",
            "bucket_id":source_bucket_id,
            "response_time":T.time()-t1_get_source_bucket
        })

        for k,b in bucket.balls.items():
            t1_get_ball = T.time()
            logger.info({
                "event":"GET.BALL",
                "bucket_id":source_bucket_id,
                "ball_id":b.ball_id,
                "response_time":T.time()-t1_get_ball,
                "sink_path":axo_sink_path_sink_bucket_id_path
            })

        

        f      = getattr(obj, envelope.method )
        base_f = inspect.unwrap(f)
        f      = __axo_method(base_f)



        for attr_name, attr_value in attrs.items():
            setattr(obj, attr_name, attr_value) 
        # print("ATTRS",type(attrs),"VALUE",attrs)
        logger.debug({
            "event":"OBJECT.METADATA",
            "args":list(map(str,task.fargs)),
            "kwargs":U.dict_any_to_dict_str(task.fkwargs),
            "attrs":U.dict_any_to_dict_str(attrs)
            # **(dict(list(map(lambda x: (x[0],str(x[1])),task.fkwargs.items()))))
        })
        f_result:Result[Any, Exception]       = f(*task.fargs,**task.fkwargs)

        if f_result.is_err:
            msg = f"Failed to execute: {f.__name__}"
            e   = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR, msg=msg)
            return Err(e)
        
        #  THIS IS THE PART THAT WE NEED TO CHANGE THE VERSION. 
        result       = f_result.unwrap()

        result_bytes = CP.dumps(result)
        result_key   = _generate_id(val=None,size=12)
        f_result_put_result = await storage_service.put(
            bucket_id = sink_bucket_id,
            key       = result_key,
            value     = result_bytes,
        )


        if f_result_put_result.is_ok:
            await U.send_ok(
                socket=socket,
                msg_id=envelope.msg_id,
                operation=AxoOperationType.METHOD_EXEC,
                task_id=envelope.task_id,
                payload_frames=[result_bytes]
            )
            return Ok(True)
        else:
            error_msg = f"Failed to store the {task.metadata.get('fname','fx')} result"
            e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR,msg=error_msg)
            return Err(e)

    except Exception as e:
        error_msg = f"Uknown error: {str(e)}"
        e         = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR,msg=error_msg)
        return Err(e)




async def method_exeution(
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
    heater.warm(task_id=task.task_id)
    dependencies             = task.get_dependencies()
    deps_installation_result = install_packages(packages=dependencies)
    endpoint_id = envelope.axo_endpoint_id
    exists      = endpoint_manager.exists(endpoint_id=endpoint_id)
    if not exists:
        logger.warning({
            "event":"DEPLOY.ENDPOINT", 
            "endpoint_id":endpoint_id
        })
        res = U.__deploy_endpoint(summoner=summoner,config=config,dependencies=dependencies,endpoint_id=endpoint_id,image=config.image)

    result = await __method_execution(
        serde           = serde,
        storage_service = storage_service,
        store           = store,
        socket  = req_rep_socket,
        task            = task,
        envelope=envelope
    )
    return result