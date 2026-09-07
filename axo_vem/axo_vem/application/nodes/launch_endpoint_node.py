from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlparse

from option import Result

from axo_shared.container.errors import ContainerSpawnError
from axo_shared.container.handle import MountSpec
from axo_shared.container.spawner import ContainerSpawner
from axo_shared.runtime.spec import ContainerMode

from axo_vem.application.nodes.deployment_defaults import DEPLOYMENT_DEFAULTS, MESH_IDENTITY_KEYS
from axo_vem.domain.compute.endpoint import Endpoint
from axo_vem.domain.compute.repository import EndpointRepository


def _reachable_pub_address(peer: Endpoint) -> Optional[str]:
    """Rebuilds a peer's externally-reachable PUB address from its own stored
    (bind-shaped, e.g. tcp://0.0.0.0:5556) pub_bind -- the mesh already
    assumes endpoint_id doubles as a DNS-resolvable hostname on the shared
    Docker network (see axo_endpoint/service/transport/address.py's
    resolve_peer_address), so only the port needs extracting."""
    if not peer.pub_bind:
        return None
    port = urlparse(peer.pub_bind).port
    if port is None:
        return None
    return f"tcp://{peer.endpoint_id}:{port}"


@dataclass(frozen=True)
class LaunchEndpointNodeResult:
    endpoint_id: str
    container_name: str
    router_bind: str


class LaunchEndpointNodeUseCase:
    """Launches a new axo_endpoint node container via the shared
    ContainerSpawner (axo_shared.container.spawner) -- the same primitive
    axo_endpoint's own ContainerSummoner delegates to for spawning
    per-function containers, reused here to spawn a whole node instead.

    AXO_ENDPOINT_SUB_CONNECT is derived automatically (see execute()) from
    the target VE's other currently-running endpoints via endpoint_repository
    -- no caller-supplied peer list needed. Wiring the new node's peers back
    to it in turn is NOT this use case's job: it's already handled at
    runtime by axo_endpoint's own reactive PEER_ANNOUNCE/heartbeat discovery
    (App._on_new_peer/_send_peer_announce) once the new node's one-way
    SUB_CONNECT is seeded correctly.
    """

    def __init__(
        self,
        spawner: ContainerSpawner,
        image: str,
        network: str,
        mode: ContainerMode = "docker",
        default_env: Optional[Dict[str, str]] = None,
        endpoint_repository: Optional[EndpointRepository] = None,
    ) -> None:
        self._spawner = spawner
        self._image = image
        self._network = network
        self._mode = mode
        self._default_env = default_env if default_env is not None else DEPLOYMENT_DEFAULTS
        self._endpoint_repository = endpoint_repository

    def execute(
        self,
        *,
        api_uri: str,
        router_port: int = 5555,
        pub_port: int = 5556,
        results_port: int = 5557,
        virtual_environment_id: Optional[str] = None,
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> Result[LaunchEndpointNodeResult, ContainerSpawnError]:
        endpoint_id = f"axo-endpoint-{uuid.uuid4().hex[:8]}"
        router_bind = f"tcp://0.0.0.0:{router_port}"
        peer_addresses = self._peer_addresses_for(virtual_environment_id)

        overrides = {k: v for k, v in (env_overrides or {}).items() if k not in MESH_IDENTITY_KEYS}
        env = {
            **self._default_env,
            **overrides,
            "AXO_ENDPOINT_ID": endpoint_id,
            "AXO_ENDPOINT_API_URI": api_uri,
            "AXO_ENDPOINT_SUB_CONNECT": ",".join(peer_addresses),
            "AXO_ENDPOINT_ROUTER_BIND": router_bind,
            "AXO_ENDPOINT_PUB_BIND": f"tcp://0.0.0.0:{pub_port}",
            "AXO_ENDPOINT_VIRTUAL_ENV_ID": virtual_environment_id or "",
        }

        spawn_result = self._spawner.spawn(
            mode=self._mode,
            image=self._image,
            name=endpoint_id,
            env=env,
            network=self._network,
            # The launched node spawns its own function containers via its
            # own ContainerSummoner, which needs the host Docker socket.
            mounts=[MountSpec(source="/var/run/docker.sock", target="/var/run/docker.sock", mode="ro")],
        )
        return spawn_result.map(
            lambda handle: LaunchEndpointNodeResult(
                endpoint_id=endpoint_id, container_name=handle.name, router_bind=router_bind,
            )
        )

    def _peer_addresses_for(self, virtual_environment_id: Optional[str]) -> List[str]:
        if not virtual_environment_id or self._endpoint_repository is None:
            return []
        peers = self._endpoint_repository.list_by_virtual_environment(virtual_environment_id)
        addresses: List[str] = []
        for peer in peers:
            if peer.status not in (None, "running"):
                continue
            address = _reachable_pub_address(peer)
            if address is not None:
                addresses.append(address)
        return addresses
