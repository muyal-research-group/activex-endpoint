import zmq
from typing import Any
from axo_endpoint.interfaces import Heater,Task
from axo_endpoint.store import KVStore
from axo.endpoint.manager import DistributedEndpointManager
from option import Err,Ok,Result
async def add_code(
        req_rep_socket:zmq.Socket,
        heater:Heater,
        endpoint_manager:DistributedEndpointManager,
        task:Task,
        store:KVStore
)->Result[Any,Exception]:
    try:
        await req_rep_socket.send_multipart([b"activex"])
        return Ok(True)
    except Exception as e:
        return Err(e)