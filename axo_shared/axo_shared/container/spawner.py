from __future__ import annotations

import logging
from typing import Dict, List, Optional

import docker
import docker.errors
import docker.types
from option import Err, Ok, Result

from axo_shared.container.errors import ContainerSpawnError
from axo_shared.container.handle import ContainerStats, MountSpec, SpawnedContainerHandle
from axo_shared.runtime.spec import ContainerMode


def _mounts_for_swarm(mounts: List[MountSpec]) -> List[str]:
    return [f"{m.source}:{m.target}:{m.mode}" for m in mounts]


def _mounts_for_docker(mounts: List[MountSpec]) -> Dict[str, Dict[str, str]]:
    return {m.source: {"bind": m.target, "mode": m.mode} for m in mounts}


class ContainerSpawner:
    """Generic Docker/Swarm container lifecycle primitive. Narrow,
    JSON-shaped params in, Result out -- no EventBus, no application Config
    object, no caller-specific bookkeeping (naming conventions, env-var
    contracts, readiness polling, status tracking all stay with the
    caller). Exists so both axo_endpoint's ContainerSummoner (per-function
    runner containers) and axo_vem's node-launch capability
    (whole axo_endpoint node containers) can share the actual Docker SDK
    mechanics instead of each reimplementing it.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._client: Optional[docker.DockerClient] = None

    def _docker(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def spawn(
        self,
        *,
        mode: ContainerMode,
        image: str,
        name: str,
        env: Dict[str, str],
        network: Optional[str] = None,
        mounts: Optional[List[MountSpec]] = None,
        mem_limit_bytes: Optional[int] = None,
        nano_cpus: Optional[int] = None,
    ) -> Result[SpawnedContainerHandle, ContainerSpawnError]:
        mounts = mounts or []
        try:
            if mode == "swarm":
                resources = None
                if mem_limit_bytes is not None or nano_cpus is not None:
                    resources = docker.types.Resources(mem_limit=mem_limit_bytes, cpu_limit=nano_cpus)
                svc = self._docker().services.create(
                    image=image,
                    name=name,
                    env=[f"{k}={v}" for k, v in env.items()],
                    networks=[network] if network else None,
                    mounts=_mounts_for_swarm(mounts) or None,
                    resources=resources,
                )
                return Ok(SpawnedContainerHandle(name=name, mode=mode, service_id=svc.id))
            else:
                container = self._docker().containers.run(
                    image=image,
                    name=name,
                    environment=env,
                    network=network,
                    volumes=_mounts_for_docker(mounts) or None,
                    mem_limit=mem_limit_bytes,
                    nano_cpus=nano_cpus,
                    detach=True,
                    remove=False,
                )
                return Ok(SpawnedContainerHandle(name=name, mode=mode, container_id=container.id))
        except docker.errors.DockerException as exc:
            return Err(ContainerSpawnError(str(exc)))

    def stop(self, handle: SpawnedContainerHandle, timeout: int = 5) -> Result[None, ContainerSpawnError]:
        try:
            if handle.mode == "swarm" and handle.service_id:
                self._docker().services.get(handle.service_id).remove()
            elif handle.container_id:
                container = self._docker().containers.get(handle.container_id)
                container.stop(timeout=timeout)
                container.remove()
        except docker.errors.NotFound:
            pass  # already gone -- stop() is idempotent
        except docker.errors.DockerException as exc:
            return Err(ContainerSpawnError(str(exc)))
        return Ok(None)

    def restart(self, handle: SpawnedContainerHandle, timeout: int = 10) -> Result[None, ContainerSpawnError]:
        try:
            if handle.mode == "swarm" and handle.service_id:
                # force_update() is Docker's native "cycle this service's
                # replica(s)" call -- there's no separate stop/start pair for
                # a service the way there is for a plain container.
                self._docker().services.get(handle.service_id).force_update()
            elif handle.container_id:
                self._docker().containers.get(handle.container_id).restart(timeout=timeout)
        except docker.errors.DockerException as exc:
            return Err(ContainerSpawnError(str(exc)))
        return Ok(None)

    def stats(self, handle: SpawnedContainerHandle) -> Result[ContainerStats, ContainerSpawnError]:
        """One-shot snapshot (stream=False) of a running container's
        resource usage -- the same numbers `docker stats` shows. Docker's
        non-streaming stats call still populates both cpu_stats and
        precpu_stats (an ~1-cycle-old sample dockerd keeps internally
        regardless of streaming mode), so CPU% is computable from a single
        call with no need for this caller to track a previous sample
        between polls itself.

        Swarm has no direct per-service equivalent (stats are inherently
        per-container/per-task), so this only supports container_id
        handles -- the only mode LaunchEndpointNodeUseCase actually spawns
        with today.
        """
        if handle.mode == "swarm" or not handle.container_id:
            return Err(ContainerSpawnError("stats() is only supported for docker-mode container handles"))
        try:
            container = self._docker().containers.get(handle.container_id)
            raw = container.stats(stream=False)
        except docker.errors.NotFound:
            return Err(ContainerSpawnError(f"container {handle.container_id!r} not found"))
        except docker.errors.DockerException as exc:
            return Err(ContainerSpawnError(str(exc)))

        cpu_stats = raw.get("cpu_stats") or {}
        precpu_stats = raw.get("precpu_stats") or {}
        cpu_delta = (
            (cpu_stats.get("cpu_usage") or {}).get("total_usage", 0)
            - (precpu_stats.get("cpu_usage") or {}).get("total_usage", 0)
        )
        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
        online_cpus = cpu_stats.get("online_cpus") or len((cpu_stats.get("cpu_usage") or {}).get("percpu_usage") or [1])
        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0 if system_delta > 0 and cpu_delta > 0 else 0.0

        memory_stats = raw.get("memory_stats") or {}
        memory_detail = memory_stats.get("stats") or {}
        # Docker's raw "usage" includes reclaimable page cache -- subtracting
        # it (docker CLI's own calculateMemUsageUnixNoCache) avoids reporting
        # near-100% "memory usage" for an idle container that's simply
        # cached a lot of page data. "cache" is the cgroup v1 field name,
        # "inactive_file" the v2 equivalent.
        cache = memory_detail.get("cache", memory_detail.get("inactive_file", 0))
        memory_usage = max(0, memory_stats.get("usage", 0) - cache)
        memory_limit = memory_stats.get("limit", 0)

        networks = raw.get("networks") or {}
        network_rx = sum(iface.get("rx_bytes", 0) for iface in networks.values())
        network_tx = sum(iface.get("tx_bytes", 0) for iface in networks.values())

        return Ok(ContainerStats(
            cpu_percent=round(cpu_percent, 2),
            memory_usage=memory_usage,
            memory_limit=memory_limit,
            network_rx=network_rx,
            network_tx=network_tx,
        ))

    def get(self, mode: ContainerMode, container_or_service_id: str) -> Optional[SpawnedContainerHandle]:
        try:
            if mode == "swarm":
                svc = self._docker().services.get(container_or_service_id)
                return SpawnedContainerHandle(name=svc.name, mode=mode, service_id=svc.id)
            container = self._docker().containers.get(container_or_service_id)
            return SpawnedContainerHandle(name=container.name, mode=mode, container_id=container.id)
        except docker.errors.NotFound:
            return None

    def list(self, mode: ContainerMode, label_filter: Optional[Dict[str, str]] = None) -> List[SpawnedContainerHandle]:
        filters = {"label": [f"{k}={v}" for k, v in label_filter.items()]} if label_filter else None
        if mode == "swarm":
            services = self._docker().services.list(filters=filters)
            return [SpawnedContainerHandle(name=s.name, mode=mode, service_id=s.id) for s in services]
        containers = self._docker().containers.list(filters=filters)
        return [SpawnedContainerHandle(name=c.name, mode=mode, container_id=c.id) for c in containers]

    def ensure_image(self, image: str) -> Result[str, ContainerSpawnError]:
        try:
            self._docker().images.get(image)
            return Ok(image)
        except docker.errors.ImageNotFound:
            return Err(ContainerSpawnError(f"image {image!r} not found"))
        except docker.errors.DockerException as exc:
            return Err(ContainerSpawnError(str(exc)))

    def build_image(
        self, *, context_path: str, dockerfile: str, tag: str, buildargs: Optional[Dict[str, str]] = None,
    ) -> Result[str, ContainerSpawnError]:
        try:
            _, logs = self._docker().images.build(
                path=context_path, dockerfile=dockerfile, tag=tag, buildargs=buildargs or {}, rm=True,
            )
            for _chunk in logs:
                pass  # consume the stream so the build actually completes
            return Ok(tag)
        except docker.errors.BuildError as exc:
            return Err(ContainerSpawnError(str(exc)))
