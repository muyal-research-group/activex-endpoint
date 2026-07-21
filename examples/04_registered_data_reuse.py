import os
import pickle
import time as T

from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.dataio import IORef
from axo_endpoint.core.events import Event, InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend
from axo_endpoint.core.storage.backend import StorageKey
from axo_endpoint.service.runtime.process_runtime import ProcessFunctionRuntime

import cloudpickle

DATAIO_ROOT = "/tmp/axo_endpoint_example_registered_data"

storage_backends       = {"fs": FilesystemStorageBackend(root=DATAIO_ROOT)}
event_bus               = InMemoryEventBus()
function_result_store   = InMemoryStorageBackend()

def on_job_completed(event):
    print(f"Job completed: {event}")

event_bus.subscribe("JOB_COMPLETED", on_job_completed)

function_registry = FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=event_bus)

# DataRegistry is what a real client's `client.upload_data(...)` talks to over
# the wire (DATA_REGISTER + DATA_CHUNK_PUT); in-process here for simplicity,
# `register_and_store` drives the exact same register()+store_chunk() path a
# real client would, just with the whole blob already in memory.
data_registry = DataRegistry(
    catalog     = InMemoryStorageBackend(),
    blob_backends = storage_backends,
    event_bus   = event_bus,
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
    function_registry = function_registry,
    on_complete       = on_complete,
    scratch_root      = "/tmp/scratch",
    storage_backends  = storage_backends,
    data_registry     = data_registry,   # lets dataio.read() resolve registered refs
)


def lookup_price(params, ctx):
    # This module-level import happens inside the forked worker process,
    # where `axo_endpoint.dataio` is bound to this job's io channel.
    from axo_endpoint import dataio

    # "prices/1" == name="prices", version=1 -- the same ref every invocation
    # uses, regardless of which key it looks up this time.
    ref = IORef(kind="fs", location="prices/1", format="pickle")
    prices = dataio.read(ref)
    return prices.get(params["item"], None)


def main():
    os.makedirs(DATAIO_ROOT, exist_ok=True)

    # Register the data ONCE, ahead of any job -- this is what
    # `client.upload_data("prices", 1, pickle.dumps(catalog), format="pickle")`
    # would do from a separate process/machine talking over the wire.
    catalog = {"apple": 1.50, "banana": 0.75, "cherry": 4.20}
    register_result = data_registry.register_and_store(
        name="prices", version=1, format="pickle", kind="fs",
        data=pickle.dumps(catalog), now=T.time(),
    )
    if register_result.is_err:
        print(f"Data registration failed: {register_result.unwrap_err()}")
        return
    print(f"Registered data: {register_result.unwrap()}")

    registry_result = function_registry.register("lookup_price", 0, cloudpickle.dumps(lookup_price), T.time())
    if registry_result.is_err:
        print(f"Function registration failed: {registry_result.unwrap_err()}")
        return
    function_key = registry_result.unwrap()

    # Invoke the SAME function multiple times, against the SAME registered
    # data -- no re-registration between calls, only the lookup key changes.
    job_ids = []
    for item in ["apple", "banana", "cherry", "durian"]:
        job_id = f"job-{item}"
        result = runtime.invoke(function_key, job_id, {"item": item})
        if result.is_err:
            print(f"Invocation failed for {item!r}: {result.unwrap_err()}")
            continue
        job_ids.append((job_id, item))

    elapsed = 0
    while job_ids:
        still_pending = []
        for job_id, item in job_ids:
            f_result = function_result_store.get(
                StorageKey(id=job_id, version=function_key.version, alias=f"{job_id}_result")
            ).unwrap()
            if f_result is not None:
                print(f"{item}: {f_result}")
            else:
                still_pending.append((job_id, item))
        job_ids = still_pending
        if job_ids:
            T.sleep(1)
            elapsed += 1
            print(f"Running main loop... elapsed time: {elapsed} seconds")


if __name__ == "__main__":
    main()
