from __future__ import annotations

from option import Err, Result

from axo_shared.container.errors import ContainerSpawnError
from axo_shared.container.spawner import ContainerSpawner
from axo_shared.runtime.spec import ContainerMode


class RestartEndpointNodeUseCase:
    """Restarts an endpoint node's container/service in place (same
    container identity survives -- see StopEndpointNodeUseCase for why only
    API-launched nodes are reachable this way)."""

    def __init__(self, spawner: ContainerSpawner, mode: ContainerMode) -> None:
        self._spawner = spawner
        self._mode = mode

    def execute(self, endpoint_id: str) -> Result[None, ContainerSpawnError]:
        handle = self._spawner.get(self._mode, endpoint_id)
        if handle is None:
            return Err(ContainerSpawnError(f"endpoint {endpoint_id!r} is not managed by this API"))
        return self._spawner.restart(handle, timeout=10)
