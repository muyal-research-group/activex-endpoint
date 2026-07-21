from __future__ import annotations

from option import Err, Result

from axo_shared.container.errors import ContainerSpawnError
from axo_shared.container.spawner import ContainerSpawner
from axo_shared.runtime.spec import ContainerMode


class StopEndpointNodeUseCase:
    """Stops (and removes) an endpoint node's container/service. Only
    endpoints this API itself launched are manageable this way --
    container_name is always exactly endpoint_id by construction
    (LaunchEndpointNodeUseCase.execute()), so ContainerSpawner.get()
    naturally returns None for a docker-compose-managed node whose actual
    container name doesn't happen to match its endpoint_id -- no separate
    "is this ours" bookkeeping is needed.
    """

    def __init__(self, spawner: ContainerSpawner, mode: ContainerMode) -> None:
        self._spawner = spawner
        self._mode = mode

    def execute(self, endpoint_id: str) -> Result[None, ContainerSpawnError]:
        handle = self._spawner.get(self._mode, endpoint_id)
        if handle is None:
            return Err(ContainerSpawnError(f"endpoint {endpoint_id!r} is not managed by this API"))
        # A full node has more to shut down cleanly than a function
        # container (router/heartbeat sockets, background threads) --
        # give it longer than ContainerSpawner.stop()'s own 5s default.
        return self._spawner.stop(handle, timeout=10)
