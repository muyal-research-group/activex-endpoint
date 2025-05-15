from typing import List,Tuple
from option import Result,Ok,Err,Some,NONE
import string
import time as T
import os
import humanfriendly as HF
from nanoid import generate as nanoid
from mictlanx.v4.summoner.summoner import Summoner ,SummonContainerPayload,ExposedPort,SummonContainerResponse
from mictlanx.interfaces.payloads import MountX
from mictlanx.logger.log import Log
from dataclasses import dataclass

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

@dataclass
class EndpointInfo:
    endpoint_id: str
    req_res_port:int
    pub_sub_port:int

class EndpointManager(object):
    def __init__(self,summoner:Summoner,image:str = "nachocode/activex:endpoint-0.0.22-alpha"):
        self.summoner = summoner
        self.endpoints            = []
        self.max_endpoints        = 5
        self.image = image
        self.default_req_res_port = 16666
        self.default_pubsub_port  = 17666



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
    def deploy_endpoint_bulk(self, 
            cpu_count:int=2,
            memory:str="1GB",
            selected_node:str="0",
            dependencies:List[str]=[],
            hostname:str="*",
            # image:str= "nachocode/activex:endpoint-0.0.22-alpha",
            rf:int = 1
    )->List[EndpointInfo]:
        infos   = []
        if len(self.endpoints) >= rf:
            return self.endpoints[:rf]
        
        for i in range(rf):
            res = self.deploy_endpoint(
                cpu_count=cpu_count,
                memory=memory,
                selected_node=selected_node,
                dependencies=dependencies,
                hostname=hostname,
                image=self.image
            )
            print("DEPLOY_RESUIT", res)
            if res.is_ok:
                _res, endpoint_info = res.unwrap()
                infos.append(endpoint_info)
        return infos


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
            image:str= "nachocode/activex:endpoint-0.0.22-alpha"
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
                    ExposedPort(host_port=pub_sub_port,container_port=pub_sub_port,ip_addr=NONE, protocolo=NONE),
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
                "pubsub_port":pub_sub_port,
                "response_time":T.time()-start_time
            })
            endpoint_data = EndpointInfo(
                endpoint_id,
                req_res_port,
                pub_sub_port,
            )
            print("ENDPOINT_DATGA", endpoint_data), endpoint_data
            self.endpoints.append(endpoint_data)
            summoner_response = self.summoner.summon(
                    payload= payload,
                    mode=MICTLANX_XOLO_MODE
            )
            print("SUMMONER_RESPONSE", summoner_response)
            return Ok((summoner_response,endpoint_data))
        
        except Exception as e:
            logger.error({
                "error":str(e),
                "endpoint_id":endpoint_id,
                "req_res_port":req_res_port,
                "pubsub_port":pub_sub_port
            })
            return Err(e)