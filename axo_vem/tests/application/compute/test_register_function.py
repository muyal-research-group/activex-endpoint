import pytest
from option import Err, Ok

from axo_shared.errors import AxoError
from axo_shared.protocol import CommandResult

from axo_vem.application.compute import register_function as register_function_module
from axo_vem.application.compute.register_function import RegisterFunctionUseCase
from axo_vem.domain.compute.endpoint import Endpoint
from axo_vem.domain.errors import ConflictError, NotFoundError, NotOwnerError, UpstreamTimeoutError
from axo_vem.domain.workspace.value_objects import ResourceCapacity
from axo_vem.domain.workspace.virtual_environment import VirtualEnvironment


def _ve(ve_id="ve1", owner="user-1"):
    return VirtualEnvironment(
        virtual_environment_id=ve_id, name="dev", owner_user_id=owner,
        capacity=ResourceCapacity(cpu=1.0, ram=1, disk=1),
    )


class _FakeVeRepository:
    def __init__(self, ve=None):
        self._ve = ve

    def get(self, virtual_environment_id):
        if self._ve is not None and self._ve.virtual_environment_id == virtual_environment_id:
            return self._ve
        return None


class _FakeEndpointRepository:
    def __init__(self, endpoints=None):
        self._endpoints = endpoints or []

    def list_by_virtual_environment(self, virtual_environment_id):
        return [e for e in self._endpoints if e.virtual_environment_id == virtual_environment_id]

    def get(self, endpoint_id):
        for e in self._endpoints:
            if e.endpoint_id == endpoint_id:
                return e
        return None


def _use_case(ve=None, endpoints=None):
    return RegisterFunctionUseCase(_FakeVeRepository(ve), _FakeEndpointRepository(endpoints), 0.3)


def test_execute_raises_not_found_for_unknown_ve():
    use_case = _use_case(ve=None)
    with pytest.raises(NotFoundError):
        use_case.execute(virtual_environment_id="missing", current_user_id="user-1", name="add", code=b"...")


def test_execute_raises_not_owner_for_foreign_ve():
    use_case = _use_case(ve=_ve(owner="someone-else"))
    with pytest.raises(NotOwnerError):
        use_case.execute(virtual_environment_id="ve1", current_user_id="user-1", name="add", code=b"...")


def test_execute_raises_conflict_when_no_endpoint_assigned():
    use_case = _use_case(ve=_ve(), endpoints=[])
    with pytest.raises(ConflictError, match="no endpoint assigned"):
        use_case.execute(virtual_environment_id="ve1", current_user_id="user-1", name="add", code=b"...")


def test_execute_picks_most_recently_seen_endpoint(monkeypatch):
    older = Endpoint(endpoint_id="n1", router_bind="tcp://0.0.0.0:5555", virtual_environment_id="ve1", last_seen_at="2026-01-01T00:00:00")
    newer = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555", virtual_environment_id="ve1", last_seen_at="2026-01-02T00:00:00")
    # list_by_virtual_environment's real Mongo query already sorts -- the
    # fake mirrors that pre-sorted contract, newest first.
    use_case = _use_case(ve=_ve(), endpoints=[newer, older])

    captured = {}

    def fake_send_command(rpc_uri, command, timeout):
        captured["rpc_uri"] = rpc_uri
        return Ok(CommandResult(ok=True, metadata={"function_id": "add", "version": 1}))

    monkeypatch.setattr(register_function_module, "send_command", fake_send_command)

    result = use_case.execute(virtual_environment_id="ve1", current_user_id="user-1", name="add", code=b"...")

    assert result["endpoint_id"] == "n0"
    assert captured["rpc_uri"] == "tcp://n0:5555"


def test_execute_raises_upstream_timeout_on_send_error(monkeypatch):
    endpoint = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555", virtual_environment_id="ve1")
    use_case = _use_case(ve=_ve(), endpoints=[endpoint])
    monkeypatch.setattr(
        register_function_module, "send_command",
        lambda rpc_uri, command, timeout: Err(AxoError("timed out")),
    )

    with pytest.raises(UpstreamTimeoutError):
        use_case.execute(virtual_environment_id="ve1", current_user_id="user-1", name="add", code=b"...")


def test_execute_raises_conflict_on_command_rejection(monkeypatch):
    endpoint = Endpoint(endpoint_id="n0", router_bind="tcp://0.0.0.0:5555", virtual_environment_id="ve1")
    use_case = _use_case(ve=_ve(), endpoints=[endpoint])
    monkeypatch.setattr(
        register_function_module, "send_command",
        lambda rpc_uri, command, timeout: Ok(CommandResult(ok=False, error="storage failure")),
    )

    with pytest.raises(ConflictError, match="storage failure"):
        use_case.execute(virtual_environment_id="ve1", current_user_id="user-1", name="add", code=b"...")
