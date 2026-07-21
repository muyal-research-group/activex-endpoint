from __future__ import annotations


def resolve_peer_address(bind_address: str, peer_id: str, local_mode: bool) -> str:
    """Builds a connectable address from a peer's bind address and identity.

    The bind address (e.g. tcp://0.0.0.0:5556) supplies only the port.
    The host is always replaced:
      local_mode=True  -> tcp://localhost:<port>
      local_mode=False -> tcp://<peer_id>:<port>  (peer_id doubles as hostname in the mesh)
    """
    port = bind_address.rsplit(":", 1)[-1]
    host = "localhost" if local_mode else peer_id
    return f"tcp://{host}:{port}"
