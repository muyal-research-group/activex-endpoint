from mictlanx.v4.client import Client
from mictlanx.utils.index import Utils as UtilsX
from activexendpoint.dummy import add_dummy_module,Dummy
from activex import ActiveX
import types
from activex.contextmanager import ActiveXContextManager
from activex.endpoint import XoloEndpointManager
import cloudpickle as CP
import sys
import os

def activex_method(f):
    # @wraps(f)
    def __activex(self:ActiveX,*args,**kwargs):
        return f(self, *args,**kwargs)
    return __activex
# def activex_method(f):
    # def __in()
AXO_ENDPOINT_ID           = os.environ.get("AXO_ENDPOINT_ID","activex-endpoint-0")
AXO_ENDPOINT_PROTOCOL     = os.environ.get("AXO_ENDPOINT_PROTOCOL","tcp")
AXO_ENDPOINT_HOSTNAME     = os.environ.get("AXO_ENDPOINT_HOSTNAME","localhost")
AXO_ENDPOINT_PUBSUB_PORT  = int(os.environ.get("AXO_ENDPOINT_PUBSUB_PORT","16000"))
AXO_ENDPOINT_REQ_RES_PORT = int(os.environ.get("AXO_ENDPOINT_REQ_RES_PORT","16667"))

MICTLANX_CLIENT_ID         = os.environ.get("MICTLANX_CLIENT_ID","client-0")
MICTLANX_DEFAULT_BUCKET_ID = os.environ.get("MICTLANX_DEFAULT_BUCKET_ID","moringas")
MICTLANX_DEBUG             = bool(int(os.environ.get("MICTLANX_DEBUG","1")))
MICTLANX_MAX_WORKERS       = int(os.environ.get("MICTLANX_MAX_WORKERS","2"))
MICTLANX_LOG_PATH          = os.environ.get("MICTLANX_LOG_PATH","./log")
SOURCE_PATH                = os.environ.get("SOURCE_PATH","./source")
routers = list(UtilsX.routers_from_str(os.environ.get("MICTLANX_ROUTERS","mictlanx-router-0:localhost:60666")))
client = Client(
    client_id      = MICTLANX_CLIENT_ID,
    routers         = routers,
    debug           = MICTLANX_DEBUG,
    max_workers     = MICTLANX_MAX_WORKERS,
    bucket_id       = MICTLANX_DEFAULT_BUCKET_ID,
    log_output_path = MICTLANX_LOG_PATH    
)
def main():
    bucket_id = "jbddhwnqf606qgwr1ix42vayqmsl1ejl"

    obj_bytes_result = client.get_with_retry(bucket_id=bucket_id, key = "0ukx01xpqjz6qh4s")
    class_def_result = client.get_with_retry(
        bucket_id="jbddhwnqf606qgwr1ix42vayqmsl1ejl",
        key="class_definition1"
    )
    class_code = client.get_with_retry(
        bucket_id="jbddhwnqf606qgwr1ix42vayqmsl1ejl",
        key="class_definition_code"
    ).unwrap().value.decode()
    
    if class_def_result.is_ok:
        class_def_bytes = class_def_result.unwrap().value
        print("CLASS_CIODE", class_code )
        exec(class_code, globals())
        class_def       = CP.loads(class_def_bytes)
        add_dummy_module(module_path="__main__", class_name="IDAx",dummy_class=class_def)
        print("CLASS_DEF",class_def)
        # exec(class_def, globals())

    if obj_bytes_result.is_ok:
        obj_bytes = obj_bytes_result.unwrap().value
        print("OBJ_BYTES", len(obj_bytes))
        # obj = ActiveX.from_bytes(raw_obj=obj_bytes)
        obj = CP.loads(obj_bytes)
        print("OBJ",obj)
        # print(obj.test())


def main2():
    endpoint_manager = XoloEndpointManager()
    endpoint_manager.add_endpoint(
        endpoint_id= AXO_ENDPOINT_ID,
        hostname=AXO_ENDPOINT_HOSTNAME,
        protocol=AXO_ENDPOINT_PROTOCOL,
        pubsub_port=AXO_ENDPOINT_PUBSUB_PORT,
        req_res_port=AXO_ENDPOINT_REQ_RES_PORT
    )
    # axcm = ActiveXContextManager.local()
    axcm = ActiveXContextManager.distributed(
        endpoint_manager= endpoint_manager
    )
    obj_bytes = client.get_with_retry(
        bucket_id="y002f6e9cdt4574jaiwczb9i8dn3ar0q",
        key="5modgp9arw9nt8vl"
    ).unwrap().value
    obj_result = ActiveX.from_bytes(obj_bytes,original_f=False)

    if obj_result.is_ok:
        obj = obj_result.unwrap()
        res = ActiveX.call(obj, method_name="to_chunks",chunk_size=1000, source_bucket_id="xxx")
        print("RES_CALL", res)

    # print(obj_result.unwrap().encode_data_to_file(
    #     source_bucket_id = "xxx"
    # ))
    
if __name__ == "__main__":
    main2()


