from typing import List,Tuple,Optional
from option import Result,Ok,Err,Some,NONE
import string
import time as T
import os
import humanfriendly as HF
from nanoid import generate as nanoid
from mictlanx.v4.summoner.summoner import Summoner ,SummonContainerPayload,ExposedPort,SummonContainerResponse
from mictlanx.interfaces.payloads import MountX
# from mictlanx.logger.log import Log
from axo.errors import AxoError,AxoErrorType
from axo.log import get_logger
from dataclasses import dataclass

# AXO_ENDPOINT_ID = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-{}".format(nanoid(alphabet=string.ascii_lowercase+string.digits, size=8 )))
AXO_LOGGER_PATH = os.environ.get("AXO_LOGGER_PATH","/log")
AXO_DEBUG = bool(int(os.environ.get("AXO_DEBUG","1")))
logger = get_logger(name=__name__, ltype="JSON",debug=AXO_DEBUG,path=AXO_LOGGER_PATH)
# logger = Log(
#     console_handler_filter=lambda x: AXO_DEBUG,
#     create_folder=True,
#     error_log=True,
#     name="activex.utils",
#     path=AXO_LOGGER_PATH,
#     when=AXO_LOGGER_WHEN,
#     interval=AXO_LOGGER_INTERVAL,
# )

@dataclass
class EndpointInfo:
    endpoint_id: str
    req_res_port:int
    pub_sub_port:int

class EndpointManager(object):
    def __init__(self,axo_endpoint_id:str,summoner:Summoner,image:str = "nachocode/activex:endpoint-0.0.22-alpha"):
        self.axo_endpoint_id              = axo_endpoint_id
        self.summoner                     = summoner
        self.endpoints:List[EndpointInfo] = []
        self.max_endpoints                = 5
        self.image                        = image
        self.default_req_res_port         = 16666
        self.default_pubsub_port          = 17666



    def clean_endpoints(self,n:int=10):
        for i in range(n):
            t1 = T.time()
            container_id = "axo-endpoint-{}".format(i)
            logger.debug({
                "event":"DELETING.ENDPOINT",
                "endpoint_id":container_id
            })
            res = self.summoner.delete_container(container_id=container_id )
            logger.info({
                "event":"DELETED.ENDPOINT",
                "endpoint_id":container_id,
                "response_time": T.time() -t1 
            })
            
            # print("Deleting...{}".format(container_id,res))


    def add_endpoint(self,endpoint_id:str,req_res_port:int, pub_sub_port:int ):
        self.endpoints.append(EndpointInfo(
            endpoint_id=endpoint_id, 
            req_res_port= req_res_port,
            pub_sub_port= pub_sub_port
        ))
    def delete_endpoint(self,endpoint_id:Optional[str]=None,mode:str="docker"):
        try:
            if len(self.endpoints)<=0:
                return Ok(True)
            _endpoint_id = endpoint_id if endpoint_id else self.endpoints[-1].endpoint_id
            self.endpoints = list(filter(lambda x:x.endpoint_id!=_endpoint_id, self.endpoints))


            res = self.summoner.delete_container(container_id=_endpoint_id,mode=mode)
            if res.is_err:
                return Err(res.unwrap_err())
            return Ok(True)
        except Exception as e:
            _e = AxoError.make(error_type=AxoErrorType.INTERNAL_ERROR,msg=str(e))
            return Err(_e)
    def srink(self,rf:int = 1,mode:str="docker"):
        try:
            count =0
            for i in range(rf):
                res = self.delete_endpoint(endpoint_id=None,mode=mode)
                if res.is_err:
                    logger.error({
                        "error":str(res.unwrap_err())
                    })
                count+= int(res.is_ok)
            return Ok(count)

        except Exception as e:
            return Err(e)
    def deploy_endpoint_bulk(self, 
            cpu_count:int=2,
            memory:str="1GB",
            selected_node:str="0",
            dependencies:List[str]=[],
            hostname:str="*",
            rf:int = 1,
            network_id:str ="axo",
            mode:str = "docker",
    )->Result[List[EndpointInfo],AxoError]:
        try:
            infos   = []

            for i in range(rf):
                res = self.deploy_endpoint(
                    cpu_count=cpu_count,
                    memory=memory,
                    selected_node=selected_node,
                    dependencies=dependencies,
                    hostname=hostname,
                    image=self.image,
                    mode=mode,
                    network_id=network_id,
                )
                if res.is_ok:
                    _res, endpoint_info = res.unwrap()
                    infos.append(endpoint_info)
            return Ok(infos)
        except Exception as e:
            return Err(e)


    def deploy_endpoint(
            self,
            # summoner:Summoner,
            cpu_count:int=2,
            memory:str="1GB",
            selected_node:str="0",
            dependencies:List[str]=[],
            # pubsub_port:int=16666,
            # req_res_port:int=16667,
            hostname:str="*",
            image:str= "nachocode/axo:endpoint-0.0.2",
            mode:str = "docker",
            network_id:str = "axo"
    )->Result[Tuple[Result[SummonContainerResponse,Exception],EndpointInfo ], Exception]:
        start_time = T.time()
        current_index = len(self.endpoints)
        endpoint_id   = "axo-endpoint-{}".format(current_index)
        pub_sub_port = self.default_pubsub_port + current_index
        req_res_port = self.default_req_res_port + current_index
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
                    "AXO_PUB_SUB_PORT":str(pub_sub_port),
                    "AXO_REQ_RES_PORT": str(req_res_port),
                    "AXO_HOSTNAME": hostname,
                    "MICTLANX_SUMMONER_IP_ADDR": "mictlanx-summoner-0",
                    "MICTLANX_SUMMONER_API_VERSION": "3",
                    "MICTLANX_SUMMONER_NETWORK": "10.0.0.0/25",
                    "MICTLANX_SUMMONER_PORT": "15000",
                    "MICTLANX_SUMMONER_MODE":mode,
                    "MICTLANX_SUMMONER_PROTOCOL": "http",
                    "MICTLANX_CLIENT_ID":endpoint_id,
                    "MICTLANX_BUCKET_ID": "axo",
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
                    ExposedPort(host_port=pub_sub_port,container_port=pub_sub_port,ip_addr=NONE, protocolo=NONE),
                    ExposedPort(host_port=req_res_port,container_port=req_res_port,ip_addr=NONE, protocolo=NONE),
                ],
                force=Some(True),
                hostname=endpoint_id,
                ip_addr=Some(endpoint_id),
                labels={
                    "axo":"",
                    "axo.type":"endpoint"
                },
                memory=HF.parse_size(memory),
                mounts=[
                    MountX(
                        source=f"{endpoint_id}-log",
                        target="/log",
                        mount_type=1,
                    ),
                    MountX(
                        source=f"{endpoint_id}-data",
                        target="/data",
                        mount_type=1,
                    ),
                ],
                network_id=network_id,
                selected_node=Some(selected_node),
                shm_size=NONE,
            )
            logger.info({
                "envet":"DEPLOY.ENDPOINT",
                "endpoint_id":endpoint_id,
                "req_res_port":req_res_port,
                "pubsub_port":pub_sub_port,
                "response_time":T.time()-start_time
            })
            endpoint_data = EndpointInfo(
                endpoint_id,
                req_res_port,
                pub_sub_port,
            )
            self.endpoints.append(endpoint_data)
            summoner_response = self.summoner.summon(
                    payload= payload,
                    mode=mode
            )
            return Ok((summoner_response,endpoint_data))
        
        except Exception as e:
            logger.error({
                "error":str(e),
                "endpoint_id":endpoint_id,
                "req_res_port":req_res_port,
                "pubsub_port":pub_sub_port
            })
            return Err(e)