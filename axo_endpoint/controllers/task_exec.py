import os
import zmq
import time as T
import cloudpickle as CP
import inspect

from functools import wraps
import hashlib as H
import asyncio
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
# 
from option import Result,Ok,Err,Some,NONE
from typing import Any,Dict,List,Optional,Tuple
from nanoid import generate as nanoid 

from axo import Axo
from axo.errors import AxoError,AxoErrorType
from axo.models import AxoRequestEnvelope,MetadataX
from axo.log import get_logger
from axo.helpers import _generate_id
from axo.enums import AxoOperationType
from axo.storage.services import MictlanXStorageService
from axo.core.models import ChunkRef,BallRef 
# 
from axo_endpoint.config import Config
import axo_endpoint.utils as U
from axo_endpoint.interfaces import Heater,Task
from axo_endpoint.utils import install_packages,get_ao,dict_any_to_dict_str
from axo.endpoint.manager import DistributedEndpointManager
from axo_endpoint.store import KVStore
from axo_endpoint.store.models import MetadataKey
from axo_endpoint.serde import Serde
import axo_endpoint.constants as CONSTANTS
# 
from mictlanx import AsyncClient as MictlanXClient
from mictlanx.services import Summoner
import mictlanx.interfaces as InterfaceX
from mictlanx.utils.segmentation import Chunk
# from functools import wraps
from axo_endpoint.config import Config
from axo.log import get_logger


AXO_ENDPOINT_IMAGE = os.environ.get("AXO_ENDPOINT_IMAGE","nachocode/activex:endpoint")
AXO_ENDPOINT_ID    = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-0")
AXO_LOGGER_PATH    = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_SINK_PATH      = os.environ.get("AXO_SINK_PATH","/sink")
logger = get_logger(name=__name__,path=AXO_LOGGER_PATH,ltype="JSON")



def process_chunk_worker(source_met:InterfaceX.Metadata, config:Config, task:Task,envelope:AxoRequestEnvelope) -> Optional[Tuple[int,ChunkRef,Chunk]]:
    """
    Worker for the FIRST pass.
    Fetches a source chunk, runs the function, and returns the resulting Chunk object.
    """
    logger         = get_logger(name=f"axo-worker-{os.getpid()}",path=AXO_LOGGER_PATH,ltype="JSON")
    storage_client = MictlanXClient(
        client_id            = config.MICTLANX_CLIENT_ID,
        debug                = config.MICTLANX_DEBUG,
        log_interval         = config.MICTLANX_LOG_INTERVAL,
        log_when             = config.MICTLANX_LOG_WHEN,
        log_output_path      = config.MICTLANX_LOG_OUTPUT_PATH,
        max_workers          = config.MICTLANX_MAX_WORKERS,
        uri                  = config.MICTLANX_URI
    )
    async def _run_async_part() -> Optional[Tuple[int,ChunkRef,Chunk]]:
        try:
            # ao_source = task.ao_source
            # exec(ao_source, globals())
            # print("HERE AO SOURCE")
            ao_state      = task.ao_state
            # print("HERE AO STATE", ao_state)
            local_ao      = CP.loads(ao_state)

            index         = int(source_met.tags.get("index", "-1"))
            source_bucket = source_met.bucket_id
            ball_id       = source_met.ball_id
            key           = source_met.key
            method_name   = envelope.method
            _f             = getattr(local_ao, method_name)
            base_f        = inspect.unwrap(_f)
            f             = __axo_task(base_f)                

            if index == -1: 
                logger.warning({
                    "event":"TAG.NOT.FOUND",
                    "name":"index",
                    "bucket_id":source_bucket,
                    "ball_id":ball_id,
                    "key":key,
                    "method":method_name,
                })
                return None

            source_result = await storage_client.get_chunk(
                bucket_id = source_met.bucket_id,
                ball_id   = source_met.ball_id,
                index     = index
            )
            if source_result.is_err: 
                logger.error({
                    "error":"GET.CHUNK.FAILED",
                    "bucket_id":source_bucket,
                    "ball_id":ball_id,
                    "key":key,
                    "method":method_name,
                    "detail":str(source_result.unwrap_err()),
                })
                return None
            (chunk, _) = source_result.unwrap()
            print("Data Chunk", chunk.data.tobytes())
            
            t0 = T.time()
            f_result: Result[Any, Exception] = await f(*task.fargs, **{**task.fkwargs, "source": chunk.data, "ctx": task.ctx})

            if f_result.is_err: 
                e = f_result.unwrap_err()
                logger.error({
                    "error":"F.EXEC.FAILED",
                    "bucket_id":source_bucket,
                    "ball_id":ball_id,
                    "key":key,
                    "index":index,
                    "method":method_name,
                    "detail":str(e)
                })               
                return None
            
            result_chunk_data = f_result.unwrap()
            print("F_RESULT_DATA", result_chunk_data)

            result_ball_id = f"{ball_id}_result"
            logger.info({
                "event":"F.EXEC",
                "bucket_id":source_met.bucket_id,
                "ball_id":source_met.ball_id,
                "key":source_met.key,
                "index":index,
                "ok":f_result.is_ok,
                "response_time":T.time() - t0
            })
            result_chunk =  Chunk.from_bytes(
                data     = result_chunk_data,
                group_id = result_ball_id,
                index    = index,
                metadata = {
                    "index": str(index)
                },
                chunk_id = Some(f"{result_ball_id}_{index}")
            )

            chunk_ref = ChunkRef(
                index    = result_chunk.index,
                size     = result_chunk.size,
                checksum = result_chunk.checksum,
                tags     = result_chunk.metadata    
            )
            return (index,chunk_ref,result_chunk)
        except Exception as e:
            logger.error({
                "error":"PROCESS.CHUNK.FAILED",
                "bucket_id":source_met.bucket_id,
                "ball_id":source_met.ball_id,
                "key":source_met.key,
                "index":source_met.tags.get("index", -1),
                "method":envelope.method,
                "detail":str(e)
            })
            return None

    return asyncio.run(_run_async_part())

# --- PASS 2 WORKER: Uploading Only ---
# This worker function is also unchanged.
def upload_chunk_worker(
        processed_chunk:Chunk,
        final_checksum:str,
        total_size:int,
        num_chunks:int,
        task:Task,
        config:Config
        # storage_client:MictlanXClient,
):
    """
    Worker for the SECOND pass.
    Takes a processed chunk, updates its metadata, and uploads it.
    """
    logger = get_logger(name=f"axo-worker-{os.getpid()}",path=AXO_LOGGER_PATH,ltype="JSON")
    storage_client = MictlanXClient(
        client_id            = config.MICTLANX_CLIENT_ID,
        debug                = config.MICTLANX_DEBUG,
        log_interval         = config.MICTLANX_LOG_INTERVAL,
        log_when             = config.MICTLANX_LOG_WHEN,
        log_output_path      = config.MICTLANX_LOG_OUTPUT_PATH,
        max_workers          = config.MICTLANX_MAX_WORKERS,
        uri                  = config.MICTLANX_URI
    )
    async def _run_async_part() -> Optional[ChunkRef]:
        try:
            processed_chunk.metadata["full_checksum"] = final_checksum
            processed_chunk.metadata["total_size"] = str(total_size)
            processed_chunk.metadata["num_chunks"] = str(num_chunks)

            print("UPDATED METADATA", processed_chunk.metadata)
            print("STORAGE CLIENT", storage_client)
            put_result = await storage_client.put_single_chunk(
                bucket_id = task.ctx.sink_bucket,
                ball_id   = processed_chunk.group_id,
                chunk     = processed_chunk
            )
            print("PUT RESULT", put_result)
            if put_result.is_err: 
                logger.error({
                    "error":"PUT.CHUNK.FAILED",
                    "detail":str(put_result.unwrap_err()),
                    "bucket_id":task.ctx.sink_bucket,
                    "ball_id":processed_chunk.group_id,
                    "key":processed_chunk.chunk_id,
                    "index":processed_chunk.index,
                })             
                return None

            return ChunkRef(
                index=processed_chunk.index,
                size=processed_chunk.size,
                checksum=processed_chunk.checksum,
                tags=processed_chunk.metadata
            )
        except Exception:
            return None

    return asyncio.run(_run_async_part())


# --- Main Orchestrator Function (with Sorting) ---
async def process_chunks_in_processes(
    ball:InterfaceX.Ball,
    config:Config, 
    # f, 
    task:Task, 
    envelope:AxoRequestEnvelope,
    max_workers: int = 1
) -> List[ChunkRef]:
    """
    Processes and uploads chunks in two parallel passes, ensuring correct order.
    """
    if max_workers < 1: max_workers = 1
    loop = asyncio.get_running_loop()
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # --- PASS 1: Process all chunks in parallel ---
        logger.info(f"PASS 1: Processing {len(ball.chunks)} chunks with {max_workers} process(es)...")
        processing_tasks = [
            loop.run_in_executor(executor, process_chunk_worker, source_met, config, task,envelope)
            for source_met in ball.chunks
        ]
        processed_chunks_results = await asyncio.gather(*processing_tasks)
        processed_chunks = [c for c in processed_chunks_results if c is not None]

        if not processed_chunks:
            logger.error("No chunks were successfully processed in Pass 1.")
            return []

        # --- Intermission: Sort, then calculate checksum and size ---
        
        # **THIS IS THE CRITICAL NEW STEP**
        # Sort the processed chunks by their index to ensure correct order.
        processed_chunks.sort(key=lambda x: x[0])
        
        logger.info("Calculating final checksum and total size on sorted chunks...")
        h = H.sha256()
        total_size = 0
        for (_,_,chunk) in processed_chunks:
            h.update(chunk.data)
            total_size += chunk.size
        final_checksum = h.hexdigest()

        # --- PASS 2: Upload all (now sorted) chunks in parallel ---
        logger.info(f"PASS 2: Uploading {len(processed_chunks)} chunks with {max_workers} process(es)...")
        upload_tasks = [
            loop.run_in_executor(
                executor, upload_chunk_worker,
                chunk, final_checksum, total_size, len(processed_chunks),
                task,config 
            )
            for (_,_,chunk) in processed_chunks
        ]
        upload_results = await asyncio.gather(*upload_tasks)
        
        final_refs = [ref for ref in upload_results if ref is not None]
        # Optionally, sort the final references as well for a predictable return value
        final_refs.sort(key=lambda ref: ref.index)
        return final_refs



def __axo_task(f):
    is_async = inspect.iscoroutinefunction(f)

    @wraps(f)
    async def __inner(*args, **kwargs):
        try:
            logger.debug({
                "event": "__AXO_TASK",
                "fname": f.__name__,
                "args": ", ".join(map(repr, args)),
                **{k: repr(v) for k, v in kwargs.items()}
            })
            if is_async:
                result = await f(*args, **kwargs)
            else:
                # run sync function off the event loop
                result = await asyncio.to_thread(f, *args, **kwargs)

            # print("_______RESULT", result)
            return Ok(result)
        except Exception as e:
            logger.error({"event": "FAILED.__AXO_TASK", "detail": str(e)})
            return Err(e)

    return __inner


async def task_exec(
        endpoint_manager:DistributedEndpointManager,
        summoner:Summoner,
        heater:Heater,
        serde:Serde,
        storage_client:MictlanXClient,
        store:KVStore,
        socket:zmq.Socket,
        task:Task,
        envelope: AxoRequestEnvelope,
        config:Config,
)->Result[Any,AxoError]:
    try:
        heater.warm(task_id=task.task_id)
        dependencies             = envelope.axo_dependencies
        deps_installation_result = install_packages(packages=dependencies)

        if deps_installation_result.is_err:
            logger.warning({
                "event":"DEPENDENCIES.INSTALLATION.FAILED",
                "erro":str(deps_installation_result.unwrap_err())
            })
        endpoint_id = envelope.axo_endpoint_id
        exists      = endpoint_manager.exists(endpoint_id=endpoint_id)
        if not exists:
            logger.warning({
                "event":"DEPLOY.ENDPOINT", 
                "endpoint_id":endpoint_id
            })
            ud_endpoint_image = getattr(envelope,"axo_endpoint_image")
            chunk_ref = U.__deploy_endpoint(
                summoner     = summoner,
                config       = config,
                dependencies = dependencies,
                endpoint_id  = endpoint_id,
                image        =  ud_endpoint_image or config.AXO_ENDPOINT_IMAGE
            )

        logger.debug({
            **dict_any_to_dict_str(envelope.__dict__),
            **dict_any_to_dict_str(task.ctx.__dict__)
        })
        ao_result = await get_ao(
            store          = store,
            storage_client = storage_client,
            axo_bucket_id  = envelope.axo_bucket_id,
            axo_alias      = envelope.axo_alias,
            axo_key        = envelope.axo_key,
            axo_version    = envelope.axo_version
        )
        if ao_result.is_err:
            e  = AxoError.make(error_type=AxoErrorType.STORAGE_ERROR, msg= "Get s")
            return Err(e)
        
        (ao,source_code,attrs) = ao_result.unwrap()
        

        # f      = getattr(ao, envelope.method ) 

        # base_f = inspect.unwrap(f)
        # f      = __axo_task(base_f)

        # print("_F", f)
        # source = 
        axo_source_bucket_id = task.axo_source_bucket_id if task.ctx.ignore_ss else task.ctx.source_bucket
        axo_sink_bucket_id   = task.axo_sink_bucket_id if task.ctx.ignore_ss else task.ctx.sink_bucket
        t1_get_source_bucket = T.time()

        bucket_result = await storage_client.get_bucket_metadata(bucket_id=axo_source_bucket_id)
        if bucket_result.is_err:
            error_msg = f"Get bucket failed: {axo_source_bucket_id}"
            e         = AxoError.make(error_type=AxoErrorType.STORAGE_ERROR, msg= error_msg)
            return Err(e)
        
        bucket = bucket_result.unwrap()
        logger.info({
            "event":"GET.BUCKET",
            "bucket_id":axo_source_bucket_id,
            "balls":len(bucket),
            "response_time":T.time()-t1_get_source_bucket
        })
        if len(bucket) ==0:
            error_msg = f"Empty bucket: {axo_source_bucket_id}"
            e         = AxoError.make(error_type=AxoErrorType.STORAGE_ERROR, msg= error_msg)
            return Err(e)
        

        # Get only the first ball
        ball = list(bucket.balls.values())[0]
        # print(ball)
        method         = envelope.method
        task.ao_state  = CP.dumps(ao)
        task.ao_source = source_code
        chunk_ref = await process_chunks_in_processes(
            ball        = ball,
            config      = config,
            # f           = f,
            task        = task,
            envelope    = envelope,
            max_workers = task.ctx.parallel or 1
        )
        result_ball_id = f"{ball.ball_id}_result"

        ball_ref = BallRef(
            v         = 0,
            checksum  = chunk_ref[0].tags.get("full_checksum",""),
            ball_id   = result_ball_id,
            bucket_id = task.ctx.sink_bucket,
            chunks    =  chunk_ref,
            tags      = {
                "source_bucket": axo_source_bucket_id,
                "source_ball"  : ball.ball_id,
                "method"       : envelope.method,
                "task_id"      : task.task_id
            },
            size         = chunk_ref[0].tags.get("total_size",0),
            content_type = "application/octet-stream",
            key          = result_ball_id
            # content_type="application/octet-stream"
        )
        ball_ref_data = ball_ref.model_dump_json().encode("utf-8")
        print("BALL_REF_DATA", ball_ref_data)
        await U.send_ok(
                socket=socket,
                msg_id=envelope.msg_id,
                operation=AxoOperationType.TASK_EXEC,
                task_id=envelope.task_id,
                payload_frames=[ball_ref_data]
        )
        return Ok(True)
    except Exception as ex:
        e         = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR, msg= str(ex))
        return Err(e)
        # h = H.sha256()
        # ball_size = 0
        # for source_met in ball.chunks:
        #     index         = source_met.tags.get("index",-1)
        #     t0            = T.time()
        #     source_bucket = source_met.bucket_id
        #     ball_id       = source_met.ball_id
        #     key           = source_met.key


        #     if index == -1:
        #         logger.warning({
        #             "event":"TAG.NOT.FOUND",
        #             "name":"index",
        #             "bucket_id":source_bucket,
        #             "ball_id":ball_id,
        #             "key":key,
        #         })
        #         continue

        #     source_result = await storage_client.get_chunk(
        #         bucket_id = source_bucket,
        #         ball_id   = ball_id,
        #         index     = index
        #     )
        #     chunk_references:List[ChunkRef] = []

        #     if source_result.is_err:
        #         logger.error({
        #             "error":"GET.CHUNK.FAILED",
        #             "bucket_id":source_bucket,
        #             "ball_id":ball_id,
        #             "key":key,
        #             "method":method,
        #             "detail":str(source_result.unwrap_err()),
        #         })
        #         continue

        #     (chunk,_) = source_result.unwrap()
            
        #     source = chunk.data
        #     # GrayScaler.to_grayscale(params)
        #     f_result:Result[Any, Exception]       = await f(*task.fargs,**{**task.fkwargs,"source":source,"ctx":task.ctx})

        #     logger.info({
        #         "event":"F.EXEC",
        #         "bucket_id":source_met.bucket_id,
        #         "ball_id":source_met.ball_id,
        #         "key":source_met.key,
        #         "index":index,
        #         "ok":f_result.is_ok,
        #         "response_time":T.time() - t0
        #     })
        #     if f_result.is_ok:
        #         result_chunk_data = f_result.unwrap()
        #         print("RESULT_CHUNK_DATA",result_chunk_data)
        #         ball_size += len(result_chunk_data)

        #         h.update(result_chunk_data)
        #         sink_bucket = task.ctx.sink_bucket
        #         result_ball_id = f"{ball_id}_result"
        #         result_chunk = Chunk.from_bytes(data=result_chunk_data,group_id=result_ball_id,index=index, metadata={
        #             "index":str(index),
        #             "num_chunks":str(len(ball.chunks)),
        #             "full_checksum":"",
        #         },chunk_id=Some(f"{result_ball_id}_{index }"))
        #         chunf_ref = ChunkRef(
        #             index     = index,
        #             size = result_chunk.size,
        #             checksum= result_chunk.checksum,
        #             tags=result_chunk.metadata
        #         )
        #         t0_put_result  = T.time()
        #         put_result = await storage_client.put_single_chunk(
        #             bucket_id = sink_bucket,
        #             ball_id   = result_ball_id,
        #             chunk     = result_chunk,
        #         )
        #         if put_result.is_err:
        #             logger.error({
        #                 "error":"PUT.CHUNK.FAILED",
        #                 "detail":str(put_result.unwrap()),
        #                 "bucket_id":sink_bucket,
        #                 "ball_id":result_ball_id,
        #                 "key":result_chunk.chunk_id,
        #                 "index":index,
        #             })
        #             continue
        #         chunk_references.append(chunf_ref)
        #         logger.info({
        #             "event":"PUT.CHUNK",
        #             "bucket_id":sink_bucket,
        #             "ball_id":result_ball_id,
        #             "key":result_chunk.chunk_id,
        #             "index":index,
        #             "response_time":T.time()-t0_put_result
        #         })
        #     else:
        #         e = f_result.unwrap_err()
        #         logger.error({
        #             "error":"F.EXEC.FAILED",
        #             "bucket_id":source_met.bucket_id,
        #             "ball_id":source_met.ball_id,
        #             "key":source_met.key,
        #             "index":index,
        #             "detail":str(e)
        #         })
        #         continue


