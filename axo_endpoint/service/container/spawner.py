from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import requests

from option import Err, Ok, Result

from axo_endpoint.config import Config
from axo_shared.activity.models import (
    CONTAINER_CRASHED_EVENT,
    CONTAINER_DISMISSED_EVENT,
    CONTAINER_READY_EVENT,
    CONTAINER_SPAWNED_EVENT,
    FUNCTION_BUILD_COMPLETED_EVENT,
    FUNCTION_BUILD_FAILED_EVENT,
    FUNCTION_BUILD_STARTED_EVENT,
    FUNCTION_STOPPED_EVENT,
)
from axo_endpoint.core.consensus.concurrency import pool_metrics_key
from axo_endpoint.core.errors import ContainerError
from axo_endpoint.core.events.bus import Event as BusEvent, EventBus
from axo_shared.container.handle import MountSpec, SpawnedContainerHandle
from axo_shared.container.spawner import ContainerSpawner
from axo_shared.runtime.spec import RuntimeSpec
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event
from axo_endpoint.service.container.handle import (
    ContainerHandle,
    ContainerStatus,
    sanitize_container_name,
)

_Logger = Union[Log, DumbLogger]

_REPO_ROOT = Path(__file__).parent.parent.parent.parent


class ContainerSummoner:
    """Manages Docker containers and Swarm services for function execution.
    Delegates the actual Docker/Swarm SDK mechanics to axo_shared's generic
    ContainerSpawner -- everything here is the function-runner-specific
    layer on top: env-var contract, naming convention, health-check
    polling, and the (function_id, version)-keyed handle registry.

    Handles are keyed by (function_id, version) -- keying by function_id
    alone would let a container spawned for an older version silently keep
    serving jobs submitted against a newly re-registered version of the
    same function, since summon()/get_handle() would find and reuse that
    stale-version handle without ever comparing versions."""

    def __init__(self, config: Config, event_bus: EventBus, logger: _Logger = None) -> None:
        self._config = config
        self._event_bus = event_bus
        self._logger: _Logger = logger or DumbLogger()
        self._spawner = ContainerSpawner()
        self._handles: Dict[Tuple[str, int], List[ContainerHandle]] = {}
        self._lock = threading.Lock()
        # Per-image-tag locks so concurrent cold starts (e.g. growing a pool
        # to max_concurrency at once) that all need the same not-yet-built
        # image share one docker build instead of each kicking off its own
        # redundant, resource-competing build -- see _ensure_image().
        self._build_locks: Dict[str, threading.Lock] = {}
        self._build_locks_guard = threading.Lock()

    # ── public API ─────────────────────────────────────────────────────────────

    def summon(
        self,
        function_id: str,
        version: int,
        spec: RuntimeSpec,
    ) -> Result[ContainerHandle, ContainerError]:
        """Starts a container or Swarm service for the given function, or
        hands back a member of its existing pool. Up to spec.max_concurrency
        live members may exist for one (function_id, version) at once --
        this reuses an available (not busy, not still spawning) member if
        one exists, grows the pool if there's room, or hands back the
        least-busy member once at capacity (a new job just queues behind it
        rather than failing).

        Growth itself -- image ensure/build plus the actual Docker/Swarm
        call -- runs on a background thread (see _spawn_in_background) so
        this always returns immediately, never blocking the caller (which
        may be RouterServer's own single receive-loop thread). The returned
        handle is reserved into self._handles under the same lock that
        computed its pool_index, starting out status=STARTING (not yet
        real); callers wait on its ready_event the same way they already do
        for a still-bootstrapping container."""
        max_concurrency = max(1, spec.max_concurrency)
        self._dismiss_stale(function_id, version)

        with self._lock:
            pool = self._handles.get((function_id, version), [])
            live = [h for h in pool if h.status not in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED)]
            available = next(
                (h for h in live if h.status not in (ContainerStatus.BUSY, ContainerStatus.STARTING)), None,
            )
            if available is not None:
                return Ok(available)
            if len(live) >= max_concurrency:
                return Ok(min(live, key=lambda h: h.invocation_count))
            pool_index = len(pool)

            service_name = sanitize_container_name(function_id, version, pool_index)
            job_port = self._config.AXO_ENDPOINT_CONTAINER_JOB_PORT
            http_port = self._config.AXO_ENDPOINT_CONTAINER_FASTAPI_PORT
            handle = ContainerHandle(
                function_id=function_id,
                version=version,
                service_name=service_name,
                mode=self._config.AXO_ENDPOINT_CONTAINER_BACKEND,
                zmq_address=f"tcp://{service_name}:{job_port}",
                http_address=f"http://{service_name}:{http_port}",
                pool_index=pool_index,
                max_duration_seconds=spec.max_duration_seconds,
            )
            # Reserved here, under the same lock that computed pool_index,
            # so a concurrent summon() call for this (function_id, version)
            # sees this slot already taken instead of recomputing the same
            # pool_index and colliding on the same deterministic name.
            self._handles.setdefault((function_id, version), []).append(handle)

        threading.Thread(
            target=self._spawn_in_background,
            args=(handle, spec),
            daemon=True,
        ).start()

        return Ok(handle)

    # ── cluster-wide placement (leader-driven growth) ───────────────────────────

    def find_idle(self, function_id: str, version: int) -> Optional[ContainerHandle]:
        """Returns an available (not busy) live member of this (function,
        version)'s local pool, if one exists -- the "local reuse" fast path
        ContainerFunctionRuntime.invoke() always tries first, with no
        network involved. Returns None rather than deciding to queue or
        grow -- those are the caller's job now (queue via least_busy(),
        grow via the leader + summon_at())."""
        self._dismiss_stale(function_id, version)
        with self._lock:
            pool = self._handles.get((function_id, version), [])
            live = [h for h in pool if h.status not in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED)]
            return next(
                (h for h in live if h.status not in (ContainerStatus.BUSY, ContainerStatus.STARTING)), None,
            )

    def least_busy(self, function_id: str, version: int) -> Optional[ContainerHandle]:
        """Returns this (function, version)'s local live member with the
        fewest invocations so far -- used when the leader's placement
        decision names this same endpoint as the target (it already owns
        every slot for this function): the job queues behind the
        least-loaded of this endpoint's own containers rather than a
        pointless self-forward over JOB_FORWARD."""
        with self._lock:
            pool = self._handles.get((function_id, version), [])
            live = [h for h in pool if h.status not in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED)]
            return min(live, key=lambda h: h.invocation_count) if live else None

    def summon_at(
        self,
        function_id: str,
        version: int,
        spec: RuntimeSpec,
        pool_index: int,
    ) -> Result[ContainerHandle, ContainerError]:
        """Grows this (function, version)'s pool by one member at a
        leader-assigned pool_index -- the cluster-wide counterpart to
        summon()'s own growth branch, except the index comes from
        ConcurrencyLedger.request_slot() instead of a locally-recomputed
        len(pool), which is what makes concurrent growth on different
        endpoints (or even the same one) never collide on a container name.

        Like summon(), the actual Docker/Swarm work runs on a background
        thread (_spawn_in_background) and this returns immediately with a
        reserved, not-yet-real handle (status=STARTING)."""
        self._dismiss_stale(function_id, version)

        service_name = sanitize_container_name(function_id, version, pool_index)
        job_port = self._config.AXO_ENDPOINT_CONTAINER_JOB_PORT
        http_port = self._config.AXO_ENDPOINT_CONTAINER_FASTAPI_PORT
        handle = ContainerHandle(
            function_id=function_id,
            version=version,
            service_name=service_name,
            mode=self._config.AXO_ENDPOINT_CONTAINER_BACKEND,
            zmq_address=f"tcp://{service_name}:{job_port}",
            http_address=f"http://{service_name}:{http_port}",
            pool_index=pool_index,
            max_duration_seconds=spec.max_duration_seconds,
        )
        with self._lock:
            self._handles.setdefault((function_id, version), []).append(handle)

        threading.Thread(
            target=self._spawn_in_background,
            args=(handle, spec),
            daemon=True,
        ).start()

        return Ok(handle)

    def pool_summary(self) -> Dict[str, Dict[str, int]]:
        """Every (function, version)'s live/idle container counts, keyed by
        pool_metrics_key -- gossiped over heartbeat metrics so the leader's
        ConcurrencyLedger can prefer reusing an idle container elsewhere
        over granting new growth, and so `two_choices` placement can compare
        load across endpoints."""
        with self._lock:
            summary: Dict[str, Dict[str, int]] = {}
            for (function_id, version), pool in self._handles.items():
                live = [h for h in pool if h.status not in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED)]
                idle = [h for h in live if h.status in (ContainerStatus.READY, ContainerStatus.IDLE)]
                summary[pool_metrics_key(function_id, version)] = {"live": len(live), "idle": len(idle)}
            return summary

    def dismiss(self, handle: ContainerHandle, reason: str = "dismissed") -> None:
        """Stops and removes a container or Swarm service. ``reason`` mirrors
        ProcessFunctionRuntime._sweep's reason strings ("idle_ttl"/
        "max_invocations"), defaulting to "dismissed" for a direct/explicit
        dismissal -- forwarded onto FUNCTION_STOPPED_EVENT below (always a
        graceful teardown; a container crash is a distinct case, folded into
        FunctionDeployFailed via CONTAINER_CRASHED_EVENT elsewhere, not this
        method)."""
        with handle._lock:
            handle.status = ContainerStatus.DISMISSED

        spawned_handle = SpawnedContainerHandle(
            name=handle.service_name, mode=handle.mode,
            container_id=handle.container_id, service_id=handle.service_id,
        )
        stop_result = self._spawner.stop(spawned_handle)
        if stop_result.is_err:
            self._logger.warning_event(
                Event.Container.DISMISSED,
                component=Component.CONTAINER_SPAWNER,
                status="error",
                function_id=handle.function_id,
                error_message=str(stop_result.unwrap_err()),
            )
            return

        with self._lock:
            key = (handle.function_id, handle.version)
            pool = self._handles.get(key)
            if pool is not None:
                try:
                    pool.remove(handle)
                except ValueError:
                    pass
                if not pool:
                    del self._handles[key]

        self._logger.info_event(
            Event.Container.DISMISSED,
            component=Component.CONTAINER_SPAWNER,
            status="ok",
            function_id=handle.function_id,
            service_name=handle.service_name,
        )
        now = time.time()
        self._event_bus.emit(BusEvent(
            event_type=CONTAINER_DISMISSED_EVENT,
            payload={
                "function_id": handle.function_id, "version": handle.version,
                "service_name": handle.service_name, "pool_index": handle.pool_index,
            },
            timestamp=now,
        ))
        self._event_bus.emit(BusEvent(
            event_type=FUNCTION_STOPPED_EVENT,
            payload={"function_id": handle.function_id, "version": handle.version, "reason": reason},
            timestamp=now,
        ))

    def _dismiss_stale(self, function_id: str, version: int) -> None:
        """Actually stops and removes any CRASHED/DISMISSED members still
        sitting in this (function, version)'s pool before summon() decides
        whether to reuse or grow it. A crash only ever flips a handle's
        in-memory status (ContainerFunctionRuntime._handle_crash never
        touches Docker) -- without this, the underlying container leaks
        forever, and (before pool_index made every spawn's name unique)
        used to 409-conflict against the still-running crashed container on
        the very next respawn attempt under the same deterministic name."""
        with self._lock:
            pool = self._handles.get((function_id, version), [])
            stale = [h for h in pool if h.status in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED)]
        for handle in stale:
            self.dismiss(handle, reason="stale_before_respawn")

    def get_handle(self, function_id: str, version: int) -> Optional[ContainerHandle]:
        """Returns one live (non-crashed/dismissed) handle for this
        (function, version) if any exist -- for callers that just need "does
        a container already exist", not pool-aware dispatch (that's
        summon()'s job)."""
        with self._lock:
            for h in self._handles.get((function_id, version), []):
                if h.status not in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED):
                    return h
            return None

    def list_handles(self) -> List[ContainerHandle]:
        with self._lock:
            return [h for pool in self._handles.values() for h in pool]

    def sweep_idle(self, ttl_seconds: float, now: float) -> List[str]:
        """Dismisses containers that have been idle longer than ttl_seconds."""
        evicted: List[str] = []
        with self._lock:
            candidates = [
                h for pool in self._handles.values() for h in pool
                if h.status == ContainerStatus.IDLE
                and h.last_used > 0
                and (now - h.last_used) > ttl_seconds
            ]
        for handle in candidates:
            self.dismiss(handle, reason="idle_ttl")
            evicted.append(handle.function_id)
        return evicted

    def sweep_max_invocations(self, max_invocations: int) -> List[str]:
        """Dismisses containers that have exceeded max_invocations (0 = unlimited)."""
        if max_invocations <= 0:
            return []
        evicted: List[str] = []
        with self._lock:
            candidates = [
                h for pool in self._handles.values() for h in pool
                if h.invocation_count >= max_invocations
            ]
        for handle in candidates:
            self.dismiss(handle, reason="max_invocations")
            evicted.append(handle.function_id)
        return evicted

    def sweep_crashed(self) -> List[str]:
        """Dismisses every CRASHED handle immediately, rather than waiting
        for the next summon() call for that (function, version) to trigger
        _dismiss_stale(). Required for cluster-wide concurrency: a CRASHED
        handle is excluded from list_handles(), so a function that crashes
        and is never invoked again would otherwise leak its ConcurrencyLedger
        grant forever -- nothing else would ever report it gone."""
        evicted: List[str] = []
        with self._lock:
            candidates = [
                h for pool in self._handles.values() for h in pool
                if h.status == ContainerStatus.CRASHED
            ]
        for handle in candidates:
            self.dismiss(handle, reason="crashed")
            evicted.append(handle.function_id)
        return evicted

    def build_runner_image(self, python_version: str) -> Result[str, ContainerError]:
        """Builds the axo-runner base image for the given Python version."""
        tag = self._runner_image(python_version)
        dockerfile = str(_REPO_ROOT / "axo_endpoint" / "runner" / "Dockerfile")

        self._logger.info_event(
            Event.Container.BUILD_STARTED,
            component=Component.CONTAINER_SPAWNER,
            tag=tag,
            python_version=python_version,
        )
        t0 = time.monotonic()
        self._event_bus.emit(BusEvent(
            event_type=FUNCTION_BUILD_STARTED_EVENT,
            payload={"function_id": None, "python_version": python_version, "image_tag": tag},
            timestamp=time.time(),
        ))
        build_result = self._spawner.build_image(
            context_path=str(_REPO_ROOT), dockerfile=dockerfile, tag=tag,
            buildargs={"PYTHON_VERSION": python_version},
        )
        if build_result.is_err:
            err = ContainerError(
                str(build_result.unwrap_err()),
                context={"tag": tag, "python_version": python_version},
            )
            self._logger.error_event(
                Event.Container.BUILD_COMPLETE,
                component=Component.CONTAINER_SPAWNER,
                status="error",
                **err.to_dict(),
            )
            self._event_bus.emit(BusEvent(
                event_type=FUNCTION_BUILD_FAILED_EVENT,
                payload={
                    "function_id": None, "python_version": python_version, "image_tag": tag,
                    "error_message": err.message,
                },
                timestamp=time.time(),
            ))
            return Err(err)

        self._logger.info_event(
            Event.Container.BUILD_COMPLETE,
            component=Component.CONTAINER_SPAWNER,
            status="ok",
            tag=tag,
        )
        self._event_bus.emit(BusEvent(
            event_type=FUNCTION_BUILD_COMPLETED_EVENT,
            payload={
                "function_id": None, "python_version": python_version, "image_tag": tag,
                "duration_ms": round((time.monotonic() - t0) * 1000, 2),
            },
            timestamp=time.time(),
        ))
        return Ok(tag)

    # ── internals ──────────────────────────────────────────────────────────────

    def _runner_image(self, python_version: str) -> str:
        return f"{self._config.AXO_ENDPOINT_CONTAINER_RUNNER_IMAGE}:py{python_version}"

    def _ensure_image(self, image: str, python_version: str) -> Result[str, ContainerError]:
        """Returns Ok if the image exists locally; builds it if auto_build is
        enabled. Concurrent callers for the same image tag (e.g. every
        member of a pool cold-starting at once) serialize on a per-image
        lock -- the first one through actually builds; the rest block on
        that same lock and then find the image already there, instead of
        each starting their own redundant `docker build`."""
        ensure_result = self._spawner.ensure_image(image)
        if ensure_result.is_ok:
            return ensure_result

        if not self._config.AXO_ENDPOINT_CONTAINER_AUTO_BUILD_IMAGE:
            return Err(ContainerError(
                f"image {image!r} not found and auto-build is disabled",
                context={"image": image},
            ))

        with self._build_locks_guard:
            lock = self._build_locks.setdefault(image, threading.Lock())

        with lock:
            # Re-check: whoever held the lock before us may have just
            # finished building this exact image.
            ensure_result = self._spawner.ensure_image(image)
            if ensure_result.is_ok:
                return ensure_result
            return self.build_runner_image(python_version)

    def _spawn_in_background(self, handle: ContainerHandle, spec: RuntimeSpec) -> None:
        """Runs the slow Docker/Swarm work -- image ensure/build plus the
        actual container/service creation -- off summon()/summon_at()'s
        caller thread. Those callers already reserved `handle` into
        self._handles and returned it with status=STARTING; this fills in
        the real container_id/service_id and advances it to BOOTSTRAPPING
        (then kicks off _poll_readiness exactly as before), or -- if the
        image build or spawn itself fails -- marks it CRASHED and sets
        ready_event, mirroring _poll_readiness's own "unblock waiters
        either way" timeout branch so anything already waiting on this
        handle (ContainerFunctionRuntime._dispatch_once_ready) fails
        cleanly instead of hanging forever."""
        function_id, version = handle.function_id, handle.version
        image = spec.image or self._runner_image(spec.python_version)
        build_result = self._ensure_image(image, spec.python_version)
        if build_result.is_err:
            # _ensure_image (via build_runner_image) already logs its own
            # BUILD_STARTED/BUILD_COMPLETE(error) events -- nothing to add.
            with handle._lock:
                handle.status = ContainerStatus.CRASHED
            handle.ready_event.set()
            return

        env = {
            "AXO_ENDPOINT_ADDRESS": self._endpoint_address(),
            "AXO_RESULT_ADDRESS": self._config.AXO_ENDPOINT_CONTAINER_RESULT_BIND.replace(
                "0.0.0.0", self._endpoint_host()
            ),
            "AXO_FUNCTION_ID": function_id,
            "AXO_FUNCTION_VERSION": str(version),
            "AXO_JOB_PORT": str(self._config.AXO_ENDPOINT_CONTAINER_JOB_PORT),
            "AXO_FASTAPI_PORT": str(self._config.AXO_ENDPOINT_CONTAINER_FASTAPI_PORT),
            "AXO_DATAIO_TIMEOUT_SECONDS": str(self._config.AXO_ENDPOINT_DATAIO_TIMEOUT_SECONDS),
            **spec.env_vars,
        }

        mem_limit_bytes = spec.memory_limit_bytes or self._config.AXO_ENDPOINT_CONTAINER_MEMORY_LIMIT_BYTES
        cpu_limit = spec.cpu_limit or self._config.AXO_ENDPOINT_CONTAINER_CPU_LIMIT
        spawn_result = self._spawner.spawn(
            mode=self._config.AXO_ENDPOINT_CONTAINER_BACKEND,
            image=image,
            name=handle.service_name,
            env=env,
            network=self._config.AXO_ENDPOINT_CONTAINER_NETWORK,
            mounts=[MountSpec(
                source=self._config.AXO_ENDPOINT_CONTAINER_PIP_CACHE_VOLUME, target="/root/.cache/pip", mode="rw",
            )],
            mem_limit_bytes=mem_limit_bytes,
            nano_cpus=int(cpu_limit * 1_000_000_000),
        )
        if spawn_result.is_err:
            err = ContainerError(
                str(spawn_result.unwrap_err()),
                context={"function_id": function_id, "image": image},
            )
            self._logger.error_event(
                Event.Container.SPAWNED,
                component=Component.CONTAINER_SPAWNER,
                status="error",
                function_id=function_id,
                service_name=handle.service_name,
                **err.to_dict(),
            )
            with handle._lock:
                handle.status = ContainerStatus.CRASHED
            handle.ready_event.set()
            return

        spawned = spawn_result.unwrap()
        with handle._lock:
            handle.service_id = spawned.service_id
            handle.container_id = spawned.container_id
            handle.status = ContainerStatus.BOOTSTRAPPING

        self._logger.info_event(
            Event.Container.SPAWNED,
            component=Component.CONTAINER_SPAWNER,
            status="ok",
            function_id=function_id,
            service_name=handle.service_name,
            backend=self._config.AXO_ENDPOINT_CONTAINER_BACKEND,
            image=image,
        )
        self._event_bus.emit(BusEvent(
            event_type=CONTAINER_SPAWNED_EVENT,
            payload={"function_id": function_id, "version": version, "service_name": handle.service_name},
            timestamp=time.time(),
        ))

        threading.Thread(
            target=self._poll_readiness,
            args=(handle,),
            daemon=True,
        ).start()

    def _endpoint_host(self) -> str:
        """Returns the hostname containers should use to reach this endpoint."""
        return os.environ.get("AXO_ENDPOINT_CONTAINER_HOST", self._config.AXO_ENDPOINT_ID)

    def _endpoint_address(self) -> str:
        router_bind = self._config.AXO_ENDPOINT_ROUTER_BIND
        port = router_bind.rsplit(":", 1)[-1]
        return f"tcp://{self._endpoint_host()}:{port}"

    def _poll_readiness(self, handle: ContainerHandle) -> None:
        """Background thread: polls /health until the container is ready or times out."""
        timeout = self._config.AXO_ENDPOINT_CONTAINER_READINESS_TIMEOUT_SECONDS
        deadline = time.monotonic() + timeout
        url = f"{handle.http_address}/health"
        t0 = time.monotonic()

        while time.monotonic() < deadline:
            if handle.status in (ContainerStatus.CRASHED, ContainerStatus.DISMISSED):
                return
            try:
                resp = requests.get(url, timeout=2)
                if resp.status_code == 200:
                    elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
                    with handle._lock:
                        handle.status = ContainerStatus.READY
                    handle.ready_event.set()
                    self._logger.info_event(
                        Event.Container.READY,
                        component=Component.CONTAINER_SPAWNER,
                        function_id=handle.function_id,
                        service_name=handle.service_name,
                        elapsed_ms=elapsed_ms,
                    )
                    self._event_bus.emit(BusEvent(
                        event_type=CONTAINER_READY_EVENT,
                        payload={
                            "function_id": handle.function_id, "version": handle.version,
                            "service_name": handle.service_name,
                        },
                        timestamp=time.time(),
                    ))
                    return
            except requests.RequestException:
                pass
            time.sleep(1.0)

        # Timed out — mark as crashed
        with handle._lock:
            handle.status = ContainerStatus.CRASHED
        handle.ready_event.set()  # unblock waiters
        self._logger.error_event(
            Event.Container.CRASHED,
            component=Component.CONTAINER_SPAWNER,
            function_id=handle.function_id,
            service_name=handle.service_name,
            error_message=f"container did not become ready within {timeout}s",
        )
        self._event_bus.emit(BusEvent(
            event_type=CONTAINER_CRASHED_EVENT,
            payload={
                "function_id": handle.function_id, "version": handle.version,
                "service_name": handle.service_name,
                "error_message": f"container did not become ready within {timeout}s",
            },
            timestamp=time.time(),
        ))
