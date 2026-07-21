import pytest
from option import Err, Ok

from axo_shared.errors import AxoError
from axo_shared.protocol import CommandResult

from axo_vem.application.compute import update_function as update_function_module
from axo_vem.application.compute.update_function import UpdateFunctionUseCase
from axo_vem.domain.compute.endpoint import Endpoint
from axo_vem.domain.compute.function import Function
from axo_vem.domain.errors import NotFoundError, UpstreamTimeoutError


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


def test_execute_raises_not_found_for_unknown_function():
    use_case = UpdateFunctionUseCase(_FakeFunctionRepository(None), _FakeEndpointRepository(), 0.3)
    with pytest.raises(NotFoundError):
        use_case.execute(function_id="add", version=1, current_user_id="user-1")


def test_execute_sends_only_provided_fields(monkeypatch):
    function = Function(function_id="add", version=1, endpoint_id=["n0"])
    endpoint = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555")
    use_case = UpdateFunctionUseCase(_FakeFunctionRepository(function), _FakeEndpointRepository([endpoint]), 0.3)

    captured = {}

    def fake_send_command(rpc_uri, command, timeout):
        captured["envelope"] = command.envelope
        return Ok(CommandResult(ok=True))

    monkeypatch.setattr(update_function_module, "send_command", fake_send_command)

    use_case.execute(function_id="add", version=1, current_user_id="user-1", env_vars={"FOO": "bar"})

    assert captured["envelope"] == {"function_id": "add", "version": 1, "env_vars": {"FOO": "bar"}}


def test_execute_falls_through_to_the_next_recorded_endpoint_when_the_first_is_unreachable(monkeypatch):
    function = Function(function_id="add", version=1, endpoint_id=["n0", "n1"])
    endpoint = Endpoint(endpoint_id="n1", router_bind="tcp://0.0.0.0:5555")
    # n0 has no recorded router_bind at all -- e.g. purged/never seen by this repository.
    use_case = UpdateFunctionUseCase(_FakeFunctionRepository(function), _FakeEndpointRepository([endpoint]), 0.3)

    captured = {}

    def fake_send_command(rpc_uri, command, timeout):
        captured["rpc_uri"] = rpc_uri
        return Ok(CommandResult(ok=True))

    monkeypatch.setattr(update_function_module, "send_command", fake_send_command)

    result = use_case.execute(function_id="add", version=1, current_user_id="user-1", env_vars={"FOO": "bar"})

    assert result == {"function_id": "add", "version": 1}
    assert captured["rpc_uri"] == "tcp://n1:5555"


def test_execute_falls_through_past_an_upstream_timeout_to_the_next_candidate(monkeypatch):
    function = Function(function_id="add", version=1, endpoint_id=["n0", "n1"])
    endpoint_n0 = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555")
    endpoint_n1 = Endpoint(endpoint_id="n1", router_bind="tcp://0.0.0.0:5555")
    use_case = UpdateFunctionUseCase(
        _FakeFunctionRepository(function), _FakeEndpointRepository([endpoint_n0, endpoint_n1]), 0.3,
    )

    def fake_send_command(rpc_uri, command, timeout):
        if rpc_uri == "tcp://n0:5555":
            return Err(AxoError("timed out"))
        return Ok(CommandResult(ok=True))

    monkeypatch.setattr(update_function_module, "send_command", fake_send_command)

    result = use_case.execute(function_id="add", version=1, current_user_id="user-1", env_vars={"FOO": "bar"})

    assert result == {"function_id": "add", "version": 1}


def test_execute_raises_upstream_timeout_once_every_candidate_is_exhausted(monkeypatch):
    function = Function(function_id="add", version=1, endpoint_id=["n0", "n1"])
    endpoint_n0 = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555")
    endpoint_n1 = Endpoint(endpoint_id="n1", router_bind="tcp://0.0.0.0:5555")
    use_case = UpdateFunctionUseCase(
        _FakeFunctionRepository(function), _FakeEndpointRepository([endpoint_n0, endpoint_n1]), 0.3,
    )
    monkeypatch.setattr(
        update_function_module, "send_command", lambda rpc_uri, command, timeout: Err(AxoError("timed out")),
    )

    with pytest.raises(UpstreamTimeoutError):
        use_case.execute(function_id="add", version=1, current_user_id="user-1", env_vars={"FOO": "bar"})
