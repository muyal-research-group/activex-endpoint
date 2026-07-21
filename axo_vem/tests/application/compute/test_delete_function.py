import pytest
from option import Err, Ok

from axo_shared.errors import AxoError
from axo_shared.protocol import CommandResult

from axo_vem.application.compute import delete_function as delete_function_module
from axo_vem.application.compute.delete_function import DeleteFunctionUseCase
from axo_vem.domain.compute.endpoint import Endpoint
from axo_vem.domain.compute.function import Function
from axo_vem.domain.errors import ConflictError, NotFoundError, UpstreamTimeoutError
from axo_vem.domain.execution.job import Job, JobStatus


class _FakeFunctionRepository:
    def __init__(self, function=None):
        self._function = function

    def get(self, function_id, version):
        if self._function is not None and (self._function.function_id, self._function.version) == (function_id, version):
            return self._function
        return None


class _FakeEndpointRepository:
    def __init__(self, endpoints=None):
        self._endpoints = {e.endpoint_id: e for e in (endpoints or [])}

    def get(self, endpoint_id):
        return self._endpoints.get(endpoint_id)


class _FakeJobRepository:
    def __init__(self, jobs=None):
        self._jobs = jobs or []

    def list_by_function(self, function_id, function_version=None):
        return [
            job for job in self._jobs
            if job.function_id == function_id and (function_version is None or job.function_version == function_version)
        ]


def test_execute_raises_not_found_for_unknown_function():
    use_case = DeleteFunctionUseCase(_FakeFunctionRepository(None), _FakeEndpointRepository(), _FakeJobRepository(), 0.3)
    with pytest.raises(NotFoundError):
        use_case.execute(function_id="add", version=1, current_user_id="user-1")


def test_execute_raises_conflict_when_function_has_no_recorded_endpoint():
    function = Function(function_id="add", version=1, endpoint_id=[])
    use_case = DeleteFunctionUseCase(_FakeFunctionRepository(function), _FakeEndpointRepository(), _FakeJobRepository(), 0.3)
    with pytest.raises(ConflictError, match="no recorded endpoint"):
        use_case.execute(function_id="add", version=1, current_user_id="user-1")


def test_execute_raises_upstream_timeout_when_every_recorded_endpoint_is_unreachable():
    function = Function(function_id="add", version=1, endpoint_id=["n0"])
    use_case = DeleteFunctionUseCase(_FakeFunctionRepository(function), _FakeEndpointRepository([]), _FakeJobRepository(), 0.3)
    with pytest.raises(UpstreamTimeoutError):
        use_case.execute(function_id="add", version=1, current_user_id="user-1")


def test_execute_falls_through_to_the_next_recorded_endpoint_when_the_first_is_unreachable(monkeypatch):
    function = Function(function_id="add", version=1, endpoint_id=["n0", "n1"])
    endpoint = Endpoint(endpoint_id="n1", router_bind="tcp://0.0.0.0:5555")
    # n0 has no recorded router_bind at all -- e.g. purged/never seen by this repository.
    use_case = DeleteFunctionUseCase(_FakeFunctionRepository(function), _FakeEndpointRepository([endpoint]), _FakeJobRepository(), 0.3)

    captured = {}

    def fake_send_command(rpc_uri, command, timeout):
        captured["rpc_uri"] = rpc_uri
        return Ok(CommandResult(ok=True))

    monkeypatch.setattr(delete_function_module, "send_command", fake_send_command)

    result = use_case.execute(function_id="add", version=1, current_user_id="user-1")

    assert result == {"function_id": "add", "version": 1}
    assert captured["rpc_uri"] == "tcp://n1:5555"


def test_execute_raises_conflict_when_function_has_a_live_container():
    function = Function(function_id="add", version=1, endpoint_id=["n0"], container_status="running")
    use_case = DeleteFunctionUseCase(_FakeFunctionRepository(function), _FakeEndpointRepository(), _FakeJobRepository(), 0.3)
    with pytest.raises(ConflictError, match="live deployed container"):
        use_case.execute(function_id="add", version=1, current_user_id="user-1")


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.STARTED])
def test_execute_raises_conflict_when_function_has_an_active_job(status):
    function = Function(function_id="add", version=1, endpoint_id=["n0"])
    job = Job(job_id="j1", function_id="add", function_version=1, status=status)
    use_case = DeleteFunctionUseCase(
        _FakeFunctionRepository(function), _FakeEndpointRepository(), _FakeJobRepository([job]), 0.3,
    )
    with pytest.raises(ConflictError, match="queued or running"):
        use_case.execute(function_id="add", version=1, current_user_id="user-1")


@pytest.mark.parametrize("status", [JobStatus.COMPLETED, JobStatus.FAILED])
def test_execute_ignores_finished_jobs_for_the_active_job_check(monkeypatch, status):
    function = Function(function_id="add", version=1, endpoint_id=["n0"])
    endpoint = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555")
    job = Job(job_id="j1", function_id="add", function_version=1, status=status)
    use_case = DeleteFunctionUseCase(
        _FakeFunctionRepository(function), _FakeEndpointRepository([endpoint]), _FakeJobRepository([job]), 0.3,
    )
    monkeypatch.setattr(
        delete_function_module, "send_command",
        lambda rpc_uri, command, timeout: Ok(CommandResult(ok=True)),
    )

    result = use_case.execute(function_id="add", version=1, current_user_id="user-1")

    assert result == {"function_id": "add", "version": 1}


def test_execute_ignores_active_jobs_for_a_different_function_version(monkeypatch):
    function = Function(function_id="add", version=1, endpoint_id=["n0"])
    endpoint = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555")
    job = Job(job_id="j1", function_id="add", function_version=2, status=JobStatus.QUEUED)
    use_case = DeleteFunctionUseCase(
        _FakeFunctionRepository(function), _FakeEndpointRepository([endpoint]), _FakeJobRepository([job]), 0.3,
    )
    monkeypatch.setattr(
        delete_function_module, "send_command",
        lambda rpc_uri, command, timeout: Ok(CommandResult(ok=True)),
    )

    result = use_case.execute(function_id="add", version=1, current_user_id="user-1")

    assert result == {"function_id": "add", "version": 1}


def test_execute_routes_via_functions_own_recorded_endpoint_not_any_other(monkeypatch):
    """The regression case: two endpoints exist, but only the function's own
    recorded endpoint_id is ever contacted -- no VE re-derivation, no
    fallback to some other node."""
    function = Function(function_id="add", version=1, endpoint_id=["n0"])
    real = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555")
    decoy = Endpoint(endpoint_id="n1", router_bind="tcp://0.0.0.0:5555")
    use_case = DeleteFunctionUseCase(
        _FakeFunctionRepository(function), _FakeEndpointRepository([real, decoy]), _FakeJobRepository(), 0.3,
    )

    captured = {}

    def fake_send_command(rpc_uri, command, timeout):
        captured["rpc_uri"] = rpc_uri
        captured["envelope"] = command.envelope
        return Ok(CommandResult(ok=True))

    monkeypatch.setattr(delete_function_module, "send_command", fake_send_command)

    result = use_case.execute(function_id="add", version=1, current_user_id="user-1")

    assert result == {"function_id": "add", "version": 1}
    assert captured["rpc_uri"] == "tcp://n0:5555"
    assert captured["envelope"] == {"function_id": "add", "version": 1}


def test_execute_raises_upstream_timeout_on_send_error(monkeypatch):
    function = Function(function_id="add", version=1, endpoint_id=["n0"])
    endpoint = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555")
    use_case = DeleteFunctionUseCase(
        _FakeFunctionRepository(function), _FakeEndpointRepository([endpoint]), _FakeJobRepository(), 0.3,
    )
    monkeypatch.setattr(
        delete_function_module, "send_command",
        lambda rpc_uri, command, timeout: Err(AxoError("timed out")),
    )

    with pytest.raises(UpstreamTimeoutError):
        use_case.execute(function_id="add", version=1, current_user_id="user-1")


def test_execute_raises_conflict_on_command_rejection(monkeypatch):
    function = Function(function_id="add", version=1, endpoint_id=["n0"])
    endpoint = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555")
    use_case = DeleteFunctionUseCase(
        _FakeFunctionRepository(function), _FakeEndpointRepository([endpoint]), _FakeJobRepository(), 0.3,
    )
    monkeypatch.setattr(
        delete_function_module, "send_command",
        lambda rpc_uri, command, timeout: Ok(CommandResult(ok=False, error="function not found")),
    )

    with pytest.raises(ConflictError, match="function not found"):
        use_case.execute(function_id="add", version=1, current_user_id="user-1")
