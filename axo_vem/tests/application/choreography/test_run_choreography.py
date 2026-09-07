import time
from types import SimpleNamespace

import pytest
from option import Ok

from axo_shared.protocol import CommandResult

import axo_vem.application.choreography.run_choreography as run_choreography_module
from axo_vem.application.choreography.cancel_choreography_run import CancelChoreographyRunUseCase
from axo_vem.application.choreography.run_choreography import RunChoreographyUseCase
from axo_vem.domain.choreography.choreography import Choreography
from axo_vem.domain.choreography.run import ACTIVE_RUN_STATUSES
from axo_vem.domain.errors import ConflictError
from axo_vem.domain.events.models import ChoreographyEdge, ChoreographyGraph, ChoreographyNode
from axo_vem.infrastructure.database.mongo.choreography_repository import MongoChoreographyRepository
from axo_vem.infrastructure.database.mongo.choreography_run_repository import MongoChoreographyRunRepository

import mongomock


def _fn_node(node_id, function_id, max_retries=0, retry_policy="constant"):
    return ChoreographyNode(
        node_id=node_id, kind="function", position={"x": 0.0, "y": 0.0},
        function_id=function_id, function_version=1, max_retries=max_retries, retry_policy=retry_policy,
    )


class _FakeChoreographyRepository:
    def __init__(self, choreography):
        self._choreography = choreography

    def get(self, choreography_id):
        return self._choreography if choreography_id == self._choreography.choreography_id else None


class _FakeFunctionRepository:
    def __init__(self, spec_by_function=None):
        self._spec_by_function = spec_by_function or {}

    def get(self, function_id, version):
        return SimpleNamespace(
            runtime_spec=self._spec_by_function.get(function_id, {"max_concurrency": 1}),
            endpoint_id=["ep1"],
        )


class _FakeEndpointRepository:
    def get(self, endpoint_id):
        return SimpleNamespace(router_bind="tcp://0.0.0.0:5555")


class _FakeSubmitUseCase:
    """Mints a fresh job_id per function_id -- deterministic and unique
    enough to route each fake send_command response independently."""

    def __init__(self):
        self.calls = []
        self._counter = 0

    def execute(self, *, function_id, version, params):
        self._counter += 1
        job_id = f"job-{function_id}-{self._counter}"
        self.calls.append({"function_id": function_id, "params": params, "job_id": job_id})
        return {"endpoint_id": "ep1", "job_id": job_id}


def _choreography(graph, choreography_id="c1", name="test-choreo"):
    return Choreography(
        choreography_id=choreography_id, name=name, owner_user_id="user-1",
        graph=graph, created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )


def _repos():
    db = mongomock.MongoClient()["test"]
    return (
        MongoChoreographyRepository(db["choreographies"]),
        MongoChoreographyRunRepository(db["choreography_runs"]),
    )


def _wait_for_terminal(run_repository, run_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = run_repository.get(run_id)
        if run.status not in ("pending", "running"):
            return run
        time.sleep(0.02)
    raise AssertionError("run did not reach a terminal status in time")


@pytest.fixture(autouse=True)
def _patch_rpc(monkeypatch):
    monkeypatch.setattr(run_choreography_module, "resolve_rpc_uri", lambda bind, endpoint_id: bind)


def _make_use_case(choreography, job_outcomes, function_specs=None):
    """job_outcomes maps job_id -> ('completed'|'failed', value_or_error)."""
    choreo_repo, run_repo = _repos()
    choreo_repo.save(choreography)
    submit_use_case = _FakeSubmitUseCase()

    def fake_send_command(rpc_uri, command, timeout):
        if command.operation == "JOB_RESULT":
            job_id = command.envelope["job_id"]
            outcome, payload = job_outcomes.get(job_id, ("completed", None))
            if outcome == "completed":
                return Ok(CommandResult(ok=True, metadata={
                    "status": "COMPLETED", "output": {"value": payload, "type": "json"},
                    "warnings": [], "duration_ms": 1.0,
                }))
            return Ok(CommandResult(ok=True, metadata={"status": "FAILED", "error": str(payload)}))
        return Ok(CommandResult(ok=True, metadata={}))

    import axo_vem.application.choreography.run_choreography as mod
    mod.send_command = fake_send_command

    use_case = RunChoreographyUseCase(
        choreography_repository=choreo_repo,
        run_repository=run_repo,
        function_repository=_FakeFunctionRepository(function_specs),
        endpoint_repository=_FakeEndpointRepository(),
        data_item_repository=SimpleNamespace(list_by_bucket=lambda name: []),
        submit_function_job_use_case=submit_use_case,
    )
    return use_case, run_repo, submit_use_case


def test_linear_chain_passes_upstream_result_into_downstream_param():
    graph = ChoreographyGraph(
        nodes=[_fn_node("a", "fn-a"), _fn_node("b", "fn-b")],
        edges=[ChoreographyEdge(edge_id="e1", source_node_id="a", target_node_id="b", kind="fn_to_fn", target_param="x")],
    )
    choreography = _choreography(graph)
    use_case, run_repo, submit_use_case = _make_use_case(
        choreography, job_outcomes={"job-fn-a-1": ("completed", 42), "job-fn-b-2": ("completed", "done")},
    )

    result = use_case.execute(choreography_id="c1", current_user_id="user-1")
    run = _wait_for_terminal(run_repo, result["run_id"])

    assert run.status == "completed"
    b_call = next(c for c in submit_use_case.calls if c["function_id"] == "fn-b")
    assert b_call["params"] == {"x": 42}


def test_failed_node_cancels_downstream_but_not_independent_branch():
    graph = ChoreographyGraph(
        nodes=[_fn_node("a", "fn-a"), _fn_node("b", "fn-b"), _fn_node("c", "fn-c")],
        edges=[ChoreographyEdge(edge_id="e1", source_node_id="a", target_node_id="b", kind="fn_to_fn", target_param="x")],
    )
    choreography = _choreography(graph)
    use_case, run_repo, submit_use_case = _make_use_case(
        choreography,
        job_outcomes={"job-fn-a-1": ("failed", "boom"), "job-fn-c-2": ("completed", "ok")},
    )

    result = use_case.execute(choreography_id="c1", current_user_id="user-1")
    run = _wait_for_terminal(run_repo, result["run_id"])

    assert run.status == "failed"
    assert run.node_states["a"].status == "failed"
    assert run.node_states["b"].status == "cancelled"
    assert run.node_states["c"].status == "completed"
    assert not any(c["function_id"] == "fn-b" for c in submit_use_case.calls)


def test_concurrency_violation_rejects_the_run_outright():
    graph = ChoreographyGraph(
        nodes=[_fn_node("a", "fn-a"), _fn_node("b", "fn-b")],
        edges=[
            ChoreographyEdge(edge_id="e1", source_node_id="a", target_node_id="b", kind="fn_to_fn"),
            ChoreographyEdge(edge_id="e2", source_node_id="a", target_node_id="b", kind="fn_to_fn"),
        ],
    )
    choreography = _choreography(graph)
    use_case, run_repo, _ = _make_use_case(
        choreography, job_outcomes={}, function_specs={"fn-a": {"max_concurrency": 1}, "fn-b": {"max_concurrency": 1}},
    )

    with pytest.raises(ConflictError):
        use_case.execute(choreography_id="c1", current_user_id="user-1")


def test_second_run_rejected_while_one_is_active():
    graph = ChoreographyGraph(nodes=[_fn_node("a", "fn-a")], edges=[])
    choreography = _choreography(graph)
    use_case, run_repo, _ = _make_use_case(choreography, job_outcomes={"job-fn-a-1": ("completed", 1)})

    use_case.execute(choreography_id="c1", current_user_id="user-1")
    with pytest.raises(ConflictError):
        use_case.execute(choreography_id="c1", current_user_id="user-1")


def test_cancel_run_stops_further_dispatch():
    graph = ChoreographyGraph(
        nodes=[_fn_node("a", "fn-a"), _fn_node("b", "fn-b")],
        edges=[ChoreographyEdge(edge_id="e1", source_node_id="a", target_node_id="b", kind="fn_to_fn", target_param="x")],
    )
    choreography = _choreography(graph)
    # "a" never resolves (always PENDING) so the run stays active until cancelled.
    use_case, run_repo, submit_use_case = _make_use_case(choreography, job_outcomes={})

    def fake_send_command(rpc_uri, command, timeout):
        if command.operation == "JOB_RESULT":
            return Ok(CommandResult(ok=True, metadata={"status": "PENDING"}))
        return Ok(CommandResult(ok=True, metadata={}))

    run_choreography_module.send_command = fake_send_command
    use_case._poll_interval_seconds = 0.01

    choreo_repo = _FakeChoreographyRepository(choreography)
    cancel_use_case = CancelChoreographyRunUseCase(
        choreography_repository=choreo_repo, run_repository=run_repo, run_use_case=use_case,
    )

    result = use_case.execute(choreography_id="c1", current_user_id="user-1")
    run_id = result["run_id"]
    time.sleep(0.1)  # let the orchestrator thread actually dispatch "a" and start polling

    cancel_use_case.execute(run_id=run_id, current_user_id="user-1")
    run = run_repo.get(run_id)
    assert run.status == "cancelled"
    assert not any(c["function_id"] == "fn-b" for c in submit_use_case.calls)
