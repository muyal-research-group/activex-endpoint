from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from axo_shared import wire
from axo_shared.protocol import Command

from axo_vem.application.compute.submit_function_job import SubmitFunctionJobUseCase
from axo_vem.domain.choreography.choreography import Choreography
from axo_vem.domain.choreography.concurrency_check import check_concurrency
from axo_vem.domain.choreography.graph_ops import downstream_of, topological_waves
from axo_vem.domain.choreography.repository import ChoreographyRepository
from axo_vem.domain.choreography.retry_policy import next_delay_seconds
from axo_vem.domain.choreography.run import (
    CANCELLED,
    COMPLETED,
    FAILED,
    PENDING,
    RUNNING,
    ChoreographyRun,
    NodeRunState,
)
from axo_vem.domain.choreography.run_repository import ChoreographyRunRepository
from axo_vem.domain.compute.repository import EndpointRepository, FunctionRepository
from axo_vem.domain.data.repository import DataItemRepository
from axo_vem.domain.errors import ConflictError, NotFoundError
from axo_vem.infrastructure.transport.ws.broadcaster import Broadcaster
from axo_vem.infrastructure.transport.zmq_command.endpoint_client import resolve_rpc_uri, send_command


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunChoreographyUseCase:
    """Orchestrates one execution of a saved Choreography.

    Deliberately NOT event-sourced -- unlike every other aggregate in this
    project, a run's state is live, fast-changing telemetry (per-node
    status while jobs are actually in flight), not a fact worth replaying
    from Kurrent. It's a plain Mongo-backed ChoreographyRun doc, updated
    directly and pushed live over a WS channel -- the same "direct
    poller/pusher" shape EndpointStatsPoller already uses for live Docker
    stats, not the event-driven bucket_handler.apply()-style projector path.

    Dispatch reuses SubmitFunctionJobUseCase verbatim (same endpoint
    resolution a manual JOB_SUBMIT already goes through); each job's real
    result is fetched the same way jobs.py's poll_job_result does, since
    the Job read-model itself never stores result values, only status/
    timing -- there is no shortcut around a live JOB_RESULT poll.

    A saved graph's own topological_waves() already guarantees a node's
    dependents land in a strictly later wave than the node itself, so a
    node that fails never has an already-dispatched dependent to cancel
    mid-wave -- cascade-cancellation only ever has to stop future waves
    from starting, never interrupt a sibling.
    """

    def __init__(
        self,
        choreography_repository: ChoreographyRepository,
        run_repository: ChoreographyRunRepository,
        function_repository: FunctionRepository,
        endpoint_repository: EndpointRepository,
        data_item_repository: DataItemRepository,
        submit_function_job_use_case: SubmitFunctionJobUseCase,
        broadcaster: Optional[Broadcaster] = None,
        command_timeout_seconds: float = 3.0,
        poll_interval_seconds: float = 0.5,
        job_timeout_seconds: float = 60.0,
    ) -> None:
        self._choreographies = choreography_repository
        self._runs = run_repository
        self._functions = function_repository
        self._endpoints = endpoint_repository
        self._data_items = data_item_repository
        self._submit_use_case = submit_function_job_use_case
        self._broadcaster = broadcaster
        self._command_timeout_seconds = command_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._job_timeout_seconds = job_timeout_seconds
        # run_id -> {job_id: rpc_uri}, for every job currently in flight --
        # lets CancelChoreographyRunUseCase find where to send JOB_CANCEL
        # without re-deriving endpoint resolution itself.
        self.live_jobs_by_run: Dict[str, Dict[str, str]] = {}
        self.stop_flags: Dict[str, threading.Event] = {}

    def execute(self, *, choreography_id: str, current_user_id: str) -> Dict[str, Any]:
        choreography = self._choreographies.get(choreography_id)
        if choreography is None:
            raise NotFoundError("choreography not found")
        choreography.assert_owner(current_user_id)
        if self._runs.has_active_run(choreography_id):
            raise ConflictError("choreography already has an active run")

        violations = self.validate(choreography)
        if violations:
            detail = "; ".join(
                f"node {v.node_id} needs {v.required_concurrency} concurrent slots, "
                f"max_concurrency is {v.max_concurrency}"
                for v in violations
            )
            raise ConflictError(f"concurrency validation failed: {detail}")

        run = ChoreographyRun(
            run_id=str(uuid.uuid4()),
            choreography_id=choreography_id,
            status=PENDING,
            node_states={n.node_id: NodeRunState(node_id=n.node_id) for n in choreography.graph.nodes},
            started_at=_now_iso(),
        )
        self._runs.save(run)
        self.live_jobs_by_run[run.run_id] = {}
        self.stop_flags[run.run_id] = threading.Event()

        threading.Thread(target=self._execute_run, args=(choreography, run), daemon=True).start()
        return run.to_dict()

    def validate(self, choreography: Choreography):
        """Exposed separately so a UI "Validate" action can call this
        without starting a run (POST /choreographies/{id}/validate)."""
        max_concurrency_by_function: Dict[str, int] = {}
        for node in choreography.graph.nodes:
            if node.kind != "function" or not node.function_id:
                continue
            function = self._functions.get(node.function_id, node.function_version)
            spec = function.runtime_spec if function is not None else None
            max_concurrency_by_function[node.function_id] = (spec or {}).get("max_concurrency", 1)
        return check_concurrency(choreography.graph, max_concurrency_by_function)

    # ── execution ────────────────────────────────────────────────────────

    def _broadcast(self, run_id: str, message: Dict[str, Any]) -> None:
        if self._broadcaster is not None:
            self._broadcaster.broadcast(f"choreographies:{run_id}", message)

    def _save_and_broadcast_node(self, run: ChoreographyRun, node_id: str) -> None:
        self._runs.save(run)
        state = run.node_states[node_id]
        self._broadcast(run.run_id, {"type": "node_status", **state.to_dict()})

    def _execute_run(self, choreography: Choreography, run: ChoreographyRun) -> None:
        stop_flag = self.stop_flags[run.run_id]
        run.status = RUNNING
        self._runs.save(run)
        self._broadcast(run.run_id, {"type": "run_status", "run_id": run.run_id, "status": run.status})

        nodes_by_id = {n.node_id: n for n in choreography.graph.nodes}
        node_results: Dict[str, Any] = {}
        cancelled_or_failed: set = set()
        any_failed = False

        try:
            waves = topological_waves(choreography.graph)
        except ValueError:
            waves = []
            any_failed = True

        for wave in waves:
            if stop_flag.is_set():
                break
            runnable = [nid for nid in wave if nid not in cancelled_or_failed]
            if not runnable:
                continue

            with ThreadPoolExecutor(max_workers=max(1, len(runnable))) as pool:
                futures = {
                    pool.submit(
                        self._run_node, choreography, run, nodes_by_id[nid], node_results, stop_flag,
                    ): nid
                    for nid in runnable
                }
                for future, node_id in futures.items():
                    ok = future.result()
                    if not ok:
                        any_failed = True
                        newly_cancelled = downstream_of(choreography.graph, node_id) - cancelled_or_failed
                        for cid in newly_cancelled:
                            state = run.node_states.get(cid)
                            if state is not None and state.status == PENDING:
                                state.status = CANCELLED
                                self._save_and_broadcast_node(run, cid)
                        cancelled_or_failed.update(newly_cancelled)

        run.status = CANCELLED if stop_flag.is_set() else (FAILED if any_failed else COMPLETED)
        run.finished_at = _now_iso()
        self._runs.save(run)
        self._broadcast(run.run_id, {"type": "run_status", "run_id": run.run_id, "status": run.status})
        self.live_jobs_by_run.pop(run.run_id, None)
        self.stop_flags.pop(run.run_id, None)

    def _run_node(
        self,
        choreography: Choreography,
        run: ChoreographyRun,
        node,
        node_results: Dict[str, Any],
        stop_flag: threading.Event,
    ) -> bool:
        """Runs one node to completion (with its own retries), returns
        whether it ultimately succeeded. Populates node_results[node.node_id]
        for any downstream fn_to_fn consumer."""
        state = run.node_states[node.node_id]
        state.status = RUNNING
        self._save_and_broadcast_node(run, node.node_id)

        if node.kind == "bucket":
            # A bucket node's own "completion" is purely structural (its
            # dependency, if any, already finished by the time its wave is
            # reached) -- nothing to dispatch for the bucket itself.
            state.status = COMPLETED
            self._save_and_broadcast_node(run, node.node_id)
            return True

        inbound = [e for e in choreography.graph.edges if e.target_node_id == node.node_id]
        bucket_edges = [e for e in inbound if e.kind == "bucket_to_fn"]
        fn_edges = [e for e in inbound if e.kind == "fn_to_fn"]

        base_params: Dict[str, Any] = {}
        for edge in fn_edges:
            if edge.target_param:
                base_params[edge.target_param] = node_results.get(edge.source_node_id)

        if not bucket_edges:
            ok, value, error = self._dispatch_with_retries(run.run_id, node, base_params, state, stop_flag)
            if ok:
                node_results[node.node_id] = value
                self._write_fn_to_bucket_edges(choreography, node, value)
            state.status = COMPLETED if ok else FAILED
            state.error = error
            self._save_and_broadcast_node(run, node.node_id)
            return ok

        # bucket_to_fn: one dispatch per selected item, up to the edge's
        # configured parallelism concurrently. The node's own result for any
        # further downstream fn_to_fn consumer is the list of all item
        # results -- there's no single "the" result once a node fans out
        # over a bucket's contents (not explicitly designed beyond this;
        # the simplest reasonable extrapolation of the settled semantics).
        all_ok = True
        item_results: List[Any] = []
        for edge in bucket_edges:
            source_node = next((n for n in choreography.graph.nodes if n.node_id == edge.source_node_id), None)
            bucket_name = source_node.bucket_name if source_node else None
            items = self._resolve_bucket_items(bucket_name, source_node)
            if not edge.target_param or not items:
                continue

            def _process_item(item):
                params = dict(base_params)
                params[edge.target_param] = {"kind": item.kind, "location": item.name, "format": item.format}
                return self._dispatch_with_retries(run.run_id, node, params, state, stop_flag)

            with ThreadPoolExecutor(max_workers=max(1, edge.parallelism)) as pool:
                for ok, value, error in pool.map(_process_item, items):
                    all_ok = all_ok and ok
                    if ok:
                        item_results.append(value)
                    else:
                        state.error = error

        if all_ok:
            node_results[node.node_id] = item_results
            self._write_fn_to_bucket_edges(choreography, node, item_results)
        state.status = COMPLETED if all_ok else FAILED
        self._save_and_broadcast_node(run, node.node_id)
        return all_ok

    def _resolve_bucket_items(self, bucket_name: Optional[str], source_node) -> List[Any]:
        if not bucket_name:
            return []
        items = self._data_items.list_by_bucket(bucket_name)
        selected = getattr(source_node, "selected_items", None) if source_node else None
        if selected:
            wanted = {(s["name"], s["version"]) for s in selected}
            items = [item for item in items if (item.name, item.version) in wanted]
        return [item for item in items if item.status == "ready"]

    def _dispatch_with_retries(
        self, run_id: str, node, params: Dict[str, Any], state: NodeRunState, stop_flag: threading.Event,
    ):
        """Dispatches one job, retrying per the node's own max_retries/
        retry_policy on failure -- an orchestrator-local retry loop,
        distinct from (and compatible with) RuntimeSpec.max_retries's
        existing container crash/timeout retries at the runtime layer."""
        attempt = 0
        last_error = ""
        while True:
            if stop_flag.is_set():
                return False, None, "cancelled"
            ok, value, error = self._dispatch_once(run_id, node, params, state, stop_flag)
            if ok:
                return True, value, ""
            last_error = error
            if attempt >= node.max_retries:
                return False, None, last_error
            delay = next_delay_seconds(node.retry_policy, attempt + 1)
            time.sleep(delay)
            attempt += 1
            state.attempt = attempt

    def _dispatch_once(self, run_id: str, node, params: Dict[str, Any], state: NodeRunState, stop_flag: threading.Event):
        try:
            submitted = self._submit_use_case.execute(
                function_id=node.function_id, version=node.function_version, params=params,
            )
        except Exception as exc:  # ConflictError/NotFoundError/UpstreamTimeoutError from the use case
            return False, None, str(exc)

        job_id = submitted.get("job_id")
        endpoint_id = submitted.get("endpoint_id")
        state.job_id = job_id
        state.endpoint_id = endpoint_id

        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None or not endpoint.router_bind:
            return False, None, f"endpoint {endpoint_id} has no known router_bind"
        rpc_uri = resolve_rpc_uri(endpoint.router_bind, endpoint_id)

        live_jobs = self.live_jobs_by_run.setdefault(run_id, {})
        if job_id:
            live_jobs[job_id] = rpc_uri
        try:
            return self._poll_until_terminal(rpc_uri, job_id, state, stop_flag)
        finally:
            if job_id:
                live_jobs.pop(job_id, None)

    def _poll_until_terminal(self, rpc_uri: str, job_id: Optional[str], state: NodeRunState, stop_flag: threading.Event):
        deadline = time.monotonic() + self._job_timeout_seconds
        while time.monotonic() < deadline:
            if stop_flag.is_set():
                self._send_cancel(rpc_uri, job_id)
                return False, None, "cancelled"
            result = send_command(
                rpc_uri,
                Command(operation=wire.JOB_RESULT, content_type="application/json", envelope={"job_id": job_id}),
                self._command_timeout_seconds,
            )
            if result.is_err:
                return False, None, str(result.unwrap_err())
            command_result = result.unwrap()
            status = (command_result.metadata or {}).get("status")
            if status == "PENDING":
                time.sleep(self._poll_interval_seconds)
                continue
            if status == "COMPLETED":
                output = (command_result.metadata or {}).get("output", {})
                state.warnings = (command_result.metadata or {}).get("warnings", [])
                state.duration_ms = (command_result.metadata or {}).get("duration_ms")
                return True, output.get("value"), ""
            return False, None, (command_result.metadata or {}).get("error", "job failed")
        self._send_cancel(rpc_uri, job_id)
        return False, None, f"job exceeded job_timeout_seconds={self._job_timeout_seconds}"

    def _send_cancel(self, rpc_uri: str, job_id: Optional[str]) -> None:
        if not job_id:
            return
        send_command(
            rpc_uri,
            Command(operation=wire.JOB_CANCEL, content_type="application/json", envelope={"job_id": job_id}),
            self._command_timeout_seconds,
        )

    def _write_fn_to_bucket_edges(self, choreography: Choreography, node, value: Any) -> None:
        """A -> Bucket edges persist A's JSON result as a new bucket item,
        auto-named "{bucket}/{choreography_name}-{node_id}", a new version
        per run. Reuses the exact DATA_REGISTER + DATA_CHUNK_PUT dance
        buckets.py's upload_data route already drives, targeting the same
        endpoint this node's own job just ran on (buckets aren't tied to a
        specific VE the way functions are, so there's no independent
        endpoint to resolve for them -- the node's own endpoint is reused)."""
        outbound = [
            e for e in choreography.graph.edges
            if e.source_node_id == node.node_id and e.kind == "fn_to_bucket"
        ]
        if not outbound:
            return

        function = self._functions.get(node.function_id, node.function_version)
        if function is None or not function.endpoint_id:
            return
        endpoint_id = function.endpoint_id[0]
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None or not endpoint.router_bind:
            return
        rpc_uri = resolve_rpc_uri(endpoint.router_bind, endpoint_id)

        for edge in outbound:
            target = next((n for n in choreography.graph.nodes if n.node_id == edge.target_node_id), None)
            if target is None or not target.bucket_name:
                continue

            name = f"{target.bucket_name}/{choreography.name}-{node.node_id}"
            existing_versions = [
                item.version for item in self._data_items.list_by_bucket(target.bucket_name) if item.name == name
            ]
            version = (max(existing_versions) + 1) if existing_versions else 1
            payload = json.dumps(value).encode("utf-8")

            register_result = send_command(
                rpc_uri,
                Command(
                    operation=wire.DATA_REGISTER, content_type="application/json",
                    envelope={
                        "name": name, "version": version, "format": "raw", "kind": "fs",
                        "total_size": len(payload), "chunk_bytes": len(payload) or 1,
                    },
                ),
                self._command_timeout_seconds,
            )
            if register_result.is_err or not register_result.unwrap().ok:
                continue
            send_command(
                rpc_uri,
                Command(
                    operation=wire.DATA_CHUNK_PUT, content_type="application/octet-stream",
                    envelope={"name": name, "version": version, "chunk_index": 0}, payload=payload,
                ),
                self._command_timeout_seconds,
            )
