from __future__ import annotations

import threading
import time
from typing import Set

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.network import PeerInfo
from axo_endpoint.core.storage import InMemoryStorageBackend
from axo_endpoint.dispatch import InMemoryCommandDispatcher
from axo_endpoint.log import Log
from axo_endpoint.service.config import Config
from axo_endpoint.service.handlers import (
    FunctionRegisterHandler,
    JobResultHandler,
    JobSubmitHandler,
    MetricsHandler,
    PingHandler,
    build_completion_recorder,
)
from axo_endpoint.service.runtime.process_runtime import ProcessFunctionRuntime
from axo_endpoint.service.runtime.scratch import sweep_orphaned_scratch_dirs
from axo_endpoint.service.transport import wire
from axo_endpoint.service.transport.heartbeat_zmq import (
    ZmqHeartbeatPublisher,
    ZmqHeartbeatSubscriber,
    run_heartbeat_gc,
)
from axo_endpoint.service.transport.router_server import RouterServer


class App:
    """Builds and runs one complete endpoint: storage, the function registry,
    the job queue, the process runtime, and the network transport, all
    connected together."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._logger = Log(name="axo-endpoint", endpoint_id=config.AXO_ENDPOINT_ID)

        self.functions_store = InMemoryStorageBackend()
        self.results_store   = InMemoryStorageBackend()
        self.event_bus       = InMemoryEventBus()
        self.registry        = FunctionRegistry(backend=self.functions_store, event_bus=self.event_bus)

        self.dispatcher = InMemoryCommandDispatcher(
            max_queue_size = config.AXO_ENDPOINT_QUEUE_MAX_DEPTH,
            worker_count   = config.AXO_ENDPOINT_QUEUE_WORKERS,
            logger         = self._logger,
        )

        on_complete = build_completion_recorder(
            results   = self.results_store,
            event_bus = self.event_bus,
            logger    = self._logger,
        )
        self.runtime = ProcessFunctionRuntime(
            function_registry  = self.registry,
            on_complete        = on_complete,
            scratch_root       = config.AXO_ENDPOINT_SCRATCH_ROOT,
            memory_limit_bytes = config.AXO_ENDPOINT_WORKER_RLIMIT_AS_BYTES,
            cpu_limit_seconds  = config.AXO_ENDPOINT_WORKER_RLIMIT_CPU_SECONDS,
            logger             = self._logger,
        )

        self.dispatcher.register_handler(
            wire.JOB_SUBMIT,
            JobSubmitHandler(
                runtime   = self.runtime,
                results   = self.results_store,
                event_bus = self.event_bus,
                logger    = self._logger,
            ),
        )
        self.dispatcher.register_handler(
            wire.JOB_RESULT,
            JobResultHandler(results=self.results_store, logger=self._logger),
        )
        self.dispatcher.register_handler(wire.METRICS, MetricsHandler(metrics_provider=self.dispatcher.metrics))

        direct_handlers = {
            wire.PING: PingHandler(),
            wire.FUNCTION_REGISTER: FunctionRegisterHandler(registry=self.registry, logger=self._logger),
        }

        self.heartbeat_publisher  = ZmqHeartbeatPublisher(bind_address=config.AXO_ENDPOINT_PUB_BIND)
        self.heartbeat_subscriber = ZmqHeartbeatSubscriber(connect_addresses=config.AXO_ENDPOINT_SUB_CONNECT)

        self.router_server = RouterServer(
            bind_address    = config.AXO_ENDPOINT_ROUTER_BIND,
            direct_handlers = direct_handlers,
            dispatcher      = self.dispatcher,
            results         = self.results_store,
            event_bus       = self.event_bus,
            logger          = self._logger,
        )

        # Keeps track of which job ids are still running.
        self._active_job_ids: Set[str] = set()
        self._active_job_ids_lock = threading.Lock()
        self.event_bus.subscribe("JOB_SUBMITTED", self._on_job_submitted)
        self.event_bus.subscribe("JOB_COMPLETED", self._on_job_finished)
        self.event_bus.subscribe("JOB_FAILED", self._on_job_finished)

        self._stop_event = threading.Event()
        self._background_threads = []
        self._start_time: float = 0.0

    def _on_job_submitted(self, event) -> None:
        """Adds a job id to the set of currently running jobs."""
        with self._active_job_ids_lock:
            self._active_job_ids.add(event.payload["job_id"])

    def _on_job_finished(self, event) -> None:
        """Removes a job id from the set of currently running jobs."""
        with self._active_job_ids_lock:
            self._active_job_ids.discard(event.payload["job_id"])

    def run(self) -> None:
        """Starts the endpoint and blocks until stop() is called."""
        self._start_time = time.monotonic()
        self.router_server.start()
        self.heartbeat_subscriber.start()

        heartbeat_gc_interval = max(1.0, self.config.AXO_ENDPOINT_HEARTBEAT_TTL_SECONDS / 2.0)
        self._background_threads = [
            threading.Thread(target=self._heartbeat_publish_loop, daemon=True),
            threading.Thread(
                target=run_heartbeat_gc,
                args=(
                    self.heartbeat_subscriber,
                    self.config.AXO_ENDPOINT_HEARTBEAT_TTL_SECONDS,
                    heartbeat_gc_interval,
                    self._stop_event,
                ),
                daemon=True,
            ),
            threading.Thread(target=self._worker_sweep_loop, daemon=True),
            threading.Thread(target=self._scratch_sweep_loop, daemon=True),
        ]
        for thread in self._background_threads:
            thread.start()

        self._logger.info_event(
            "APP.STARTED",
            component="app",
            status="ok",
            router_bind=self.config.AXO_ENDPOINT_ROUTER_BIND,
            worker_count=self.config.AXO_ENDPOINT_QUEUE_WORKERS,
        )
        self._stop_event.wait()  # blocks until stop() is called

    def stop(self) -> None:
        """Shuts down the endpoint and waits for everything to stop cleanly."""
        self._stop_event.set()
        self.router_server.stop()
        self.heartbeat_subscriber.stop()
        self.heartbeat_publisher.close()
        self.dispatcher.close()
        for thread in self._background_threads:
            thread.join(timeout=2.0)

        uptime_ms = round((time.monotonic() - self._start_time) * 1000, 2) if self._start_time else 0.0
        self._logger.info_event(
            "APP.STOPPED",
            component="app",
            status="ok",
            duration_ms=uptime_ms,
        )

    def _heartbeat_publish_loop(self) -> None:
        """Runs in the background, sending out a heartbeat on a regular interval."""
        while not self._stop_event.is_set():
            info = PeerInfo(
                peer_id=self.config.AXO_ENDPOINT_ID,
                service_name="axo-endpoint",
                rpc_uri=self.config.AXO_ENDPOINT_ROUTER_BIND,
                metrics=self.dispatcher.metrics(),
                last_seen=time.time(),
            )
            self.heartbeat_publisher.publish(info)
            self._logger.debug_event(
                "APP.HEARTBEAT",
                component="app",
                metrics=self.dispatcher.metrics(),
            )
            self._stop_event.wait(self.config.AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS)

    def _worker_sweep_loop(self) -> None:
        """Runs in the background, cleaning up idle or overused worker processes."""
        while not self._stop_event.is_set():
            now = time.time()
            self.runtime.sweep_idle(self.config.AXO_ENDPOINT_WORKER_IDLE_TTL_SECONDS, now)
            self.runtime.sweep_max_invocations(self.config.AXO_ENDPOINT_WORKER_MAX_INVOCATIONS)
            self._stop_event.wait(self.config.AXO_ENDPOINT_WORKER_GC_INTERVAL_SECONDS)

    def _scratch_sweep_loop(self) -> None:
        """Runs in the background, deleting leftover scratch folders for jobs that are no longer active."""
        while not self._stop_event.is_set():
            with self._active_job_ids_lock:
                active = set(self._active_job_ids)
            sweep_orphaned_scratch_dirs(self.config.AXO_ENDPOINT_SCRATCH_ROOT, active)
            self._stop_event.wait(self.config.AXO_ENDPOINT_SCRATCH_GC_INTERVAL_SECONDS)


def build_app(config: Config) -> App:
    """Creates a new endpoint app from the given settings."""
    return App(config)
