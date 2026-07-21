import pytest
import zmq

from axo_shared.client import AxoEndpointClient
from axo_endpoint.core.data import DataRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.storage import FilesystemStorageBackend, InMemoryStorageBackend
from axo_endpoint.dispatch import InMemoryCommandDispatcher
from axo_endpoint.service.handlers import DataChunkPutHandler, DataRegisterHandler, DataStatusHandler, PingHandler
from axo_shared import wire
from axo_endpoint.service.transport.router_server import RouterServer


def _bind_address(tmp_path, name="router"):
    return f"ipc://{tmp_path}/{name}.sock"


@pytest.fixture
def server(tmp_path):
    registry = DataRegistry(
        catalog=InMemoryStorageBackend(),
        blob_backends={"fs": FilesystemStorageBackend(root=str(tmp_path / "dataio"))},
        event_bus=InMemoryEventBus(),
    )
    address = _bind_address(tmp_path)
    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=1)
    router = RouterServer(
        bind_address=address,
        direct_handlers={
            wire.PING: PingHandler(),
            wire.DATA_REGISTER: DataRegisterHandler(registry=registry, own_rpc_uri=address),
            wire.DATA_CHUNK_PUT: DataChunkPutHandler(registry=registry),
            wire.DATA_STATUS: DataStatusHandler(registry=registry),
        },
        dispatcher=dispatcher,
        results=InMemoryStorageBackend(),
        event_bus=InMemoryEventBus(),
    )
    router.start()
    yield address, registry
    router.stop()
    dispatcher.close()


def test_upload_data_from_bytes_round_trips(server):
    address, registry = server
    with AxoEndpointClient(address) as client:
        result = client.upload_data("df1", 1, b"hello-world", chunk_bytes=4)

    assert result.ok is True
    assert result.metadata["complete"] is True
    assert registry.read_whole("df1", 1).unwrap() == b"hello-world"


def test_upload_data_from_file_path_round_trips(server, tmp_path):
    address, registry = server
    path = tmp_path / "in.bin"
    path.write_bytes(b"some file contents on disk")

    with AxoEndpointClient(address) as client:
        result = client.upload_data("df2", 1, str(path), chunk_bytes=8)

    assert result.ok is True
    assert registry.read_whole("df2", 1).unwrap() == b"some file contents on disk"


def test_upload_data_resume_skips_already_present_chunks(server):
    address, registry = server
    with AxoEndpointClient(address) as client:
        client.register_data("df3", 1, total_size=8, chunk_bytes=4)
        client.put_data_chunk("df3", 1, 0, b"abcd")

        # Re-uploading with resume=True must not resend chunk 0.
        result = client.upload_data("df3", 1, b"abcdefgh", chunk_bytes=4, resume=True)

    assert result.ok is True
    assert registry.read_whole("df3", 1).unwrap() == b"abcdefgh"


def test_data_status_reachable(server):
    address, _ = server
    with AxoEndpointClient(address) as client:
        client.upload_data("df4", 1, b"xyz", chunk_bytes=4)
        status = client.data_status("df4", 1)

    assert status.ok is True
    assert status.metadata["complete"] is True
