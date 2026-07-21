from __future__ import annotations

import zmq
from option import Err, Result

from axo_shared import wire
from axo_shared.errors import AxoError
from axo_shared.protocol import Command, CommandResult
from axo_shared.wire import WireError


def resolve_rpc_uri(bind_address: str, endpoint_id: str) -> str:
    """A node's stored router_bind (e.g. tcp://0.0.0.0:5555) is its own bind
    address, never connectable as-is -- and every node binds the same
    internal port, so only the host distinguishes them. Every endpoint this
    service talks to is a container/service named exactly its endpoint_id
    on the shared Docker network (LaunchEndpointNodeUseCase's own spawn
    name, or a docker-compose service keyed the same way), so Docker's own
    DNS resolves it directly -- mirrors axo_endpoint's own
    resolve_peer_address, minus the local_mode branch (irrelevant here).
    """
    port = bind_address.rsplit(":", 1)[-1]
    return f"tcp://{endpoint_id}:{port}"


def send_command(rpc_uri: str, command: Command, timeout_seconds: float) -> Result[CommandResult, AxoError]:
    """Sends a command directly to an axo_endpoint node's ROUTER socket and
    waits for its reply. Mirrors axo_endpoint.service.app.App._forward_command
    (the same DEALER-connect-send-poll-decode shape used there for leader
    forwarding) -- axo_vem has no other outbound command capability
    today, since every other exchange with a node flows the other way
    (the node pushes events to the ingestion ROUTER). Returns Err on
    connect/timeout failure rather than raising. Moved verbatim from
    command/endpoint_client.py -- still imports axo_shared.wire/protocol/
    errors directly, since infrastructure has no import restriction.
    """
    sock = zmq.Context.instance().socket(zmq.DEALER)
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(rpc_uri)
    try:
        sock.send_multipart(wire.encode_command(command))
        poller = zmq.Poller()
        poller.register(sock, zmq.POLLIN)
        events = dict(poller.poll(timeout=int(timeout_seconds * 1000)))
        if sock not in events:
            return Err(WireError(f"timed out waiting for reply from {rpc_uri}"))
        frames = sock.recv_multipart()
        return wire.decode_command_result(frames)
    finally:
        sock.close()
