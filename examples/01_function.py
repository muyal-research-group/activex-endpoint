from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.storage import InMemoryStorageBackend
from axo_endpoint.core.storage.backend import StorageKey
from axo_endpoint.service.runtime.process_runtime import ProcessFunctionRuntime
from axo_endpoint.core.events import Event

import cloudpickle
import time as T


function_result_store = InMemoryStorageBackend()
event_bus             = InMemoryEventBus()

def on_job_completed(event):
    print(f"Job completed: {event}")

event_bus.subscribe("JOB_COMPLETED", on_job_completed)
registry = FunctionRegistry(
    backend   = InMemoryStorageBackend(),
    event_bus = event_bus
)


def on_complete(handle, result):
    print(f"Function completed: {handle}, result: {result}")
    key = StorageKey(id=handle.job_id, version=0, alias=f"{handle.job_id}_result")
    function_result_store.put(key, result)
    event_bus.emit(Event(
        event_type = "JOB_COMPLETED",
        payload    = {"job_id": handle.job_id, "result": result},
        timestamp  = T.time()

    ))

runtime = ProcessFunctionRuntime(
    function_registry = registry,
    on_complete       = on_complete,
    scratch_root      = "/tmp/scratch"
)

def function_to_register(params, ctx):
    import os
    import time

    print(f"Function started with params: {params}")
    time.sleep(2)  # Simulate some work
    result = {"pid": os.getpid(), "params": params}
    print("Context scratch directory:", ctx)
    return result

def main():
    elapsed         = 0
    registry_result = registry.register("test_function",0, cloudpickle.dumps(function_to_register),T.time())
    if registry_result.is_err:
        print(f"Function registration failed: {registry_result.unwrap_err()}")
        return
    
    function_key = registry_result.unwrap()
    result       = runtime.invoke(function_key, "job1", {"a": 1, "b": 2})

    if result.is_err:
        print(f"Invocation failed: {result.unwrap_err()}")
        return
    handle = result.unwrap()

    while True:
        print(f"Running main loop... elapsed time: {elapsed} seconds")
        # 
        f_result = function_result_store.get(StorageKey(id=handle.job_id, version=function_key.version, alias=f"{handle.job_id}_result")).unwrap()
        print(f"Function result store: {f_result}")
        if f_result is not None:
            print(f"Function result: {f_result}")
            break
        T.sleep(1)
        elapsed += 1

if __name__ == "__main__":
    main()