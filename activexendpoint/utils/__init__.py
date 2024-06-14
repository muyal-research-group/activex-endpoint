from typing import Generator,Any,List
from option import Result,Ok,Err,Some,NONE
import subprocess
import sys
import logging
import string
import time as T
import os
import humanfriendly as HF
from nanoid import generate as nanoid
from mictlanx.v4.summoner.summoner import Summoner ,SummonContainerPayload,ExposedPort
from mictlanx.interfaces.payloads import MountX
from mictlanx.logger.log import Log

AXO_ENDPOINT_ID = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-{}".format(nanoid(alphabet=string.ascii_lowercase+string.digits, size=8 )))
MICTLANX_XOLO_MODE = os.environ.get("MICTLANX_XOLO_MODE","docker")
AXO_LOGGER_PATH = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_LOGGER_WHEN = os.environ.get("AXO_LOGGER_WHEN","h")
AXO_LOGGER_INTERVAL = int(os.environ.get("AXO_LOGGER_INTERVAL","24"))
AXO_DEBUG = bool(int(os.environ.get("AXO_DEBUG","1")))
logger = Log(
    console_handler_filter=lambda x: AXO_DEBUG,
    create_folder=True,
    error_log=True,
    name="activex.utils",
    path=AXO_LOGGER_PATH,
    when=AXO_LOGGER_WHEN,
    interval=AXO_LOGGER_INTERVAL,
)

# logger = logging.getLogger(AXO_ENDPOINT_ID)

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
        command = "poetry add {}".format(package)
        status = subprocess.run(command, shell=True, capture_output=True, text=True)
        logger.debug({
            "event":"DEPENDENCY.INSTALLED",
            "executable":sys.executable,
            "stdout":status.stdout,
            "stderr":status.stderr,
            "dependencie": package,
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
                "MICTLANX_XOLO_MODE":MICTLANX_XOLO_MODE,
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
            mode=MICTLANX_XOLO_MODE
        )
    except Exception as e:
        logger.error({
            "error":str(e),
            "endpoint_id":endpoint_id,
            "req_res_port":req_res_port,
            "pubsub_port":pubsub_port
        })