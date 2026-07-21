from typing import List, Optional

import pytest
from option import Err, Ok

from axo_endpoint.core.consensus.elector import LeaderElector, LeaderView
from axo_endpoint.core.consensus.membership import ClusterMember
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.service.handlers.leader_proxy import LeaderProxyHandler


class FakeElector(LeaderElector):
    def __init__(self, leader_id: str) -> None:
        self._leader_id = leader_id

    @property
    def leader_set_size(self) -> int:
        return 1

    def current_view(self) -> LeaderView:
        return LeaderView(leader_ids=frozenset({self._leader_id}), term=1, decided_at=0.0)

    def recompute(self, members: List[ClusterMember], now: float) -> LeaderView:
        return self.current_view()

    def is_leader(self, peer_id: str) -> bool:
        return peer_id == self._leader_id


class FakeInnerHandler(CommandHandler):
    def __init__(self) -> None:
        self.calls: List[Command] = []

    def handle(self, command: Command) -> CommandResult:
        self.calls.append(command)
        return CommandResult(ok=True, metadata={"handled_by": "inner"})


@pytest.fixture
def command():
    return Command(operation="FUNCTION_REGISTER", content_type="application/json", envelope={"name": "foo"})


def test_calls_inner_directly_when_leader(command):
    inner = FakeInnerHandler()
    forward_calls = []

    def forward_fn(rpc_uri, cmd, timeout):
        forward_calls.append((rpc_uri, cmd, timeout))
        return Ok(CommandResult(ok=True))

    handler = LeaderProxyHandler(
        inner=inner,
        elector=FakeElector(leader_id="self"),
        self_id="self",
        resolve_leader_rpc_uri=lambda peer_id: "tcp://leader",
        forward_fn=forward_fn,
        forward_timeout_seconds=1.0,
    )

    result = handler.handle(command)

    assert result.metadata == {"handled_by": "inner"}
    assert inner.calls == [command]
    assert forward_calls == []


def test_forwards_to_leader_when_not_leader_and_relays_reply(command):
    inner = FakeInnerHandler()
    forward_calls = []

    def forward_fn(rpc_uri, cmd, timeout):
        forward_calls.append((rpc_uri, cmd, timeout))
        return Ok(CommandResult(ok=True, metadata={"handled_by": "leader"}))

    handler = LeaderProxyHandler(
        inner=inner,
        elector=FakeElector(leader_id="other"),
        self_id="self",
        resolve_leader_rpc_uri=lambda peer_id: "tcp://leader-address",
        forward_fn=forward_fn,
        forward_timeout_seconds=2.5,
    )

    result = handler.handle(command)

    assert result.metadata == {"handled_by": "leader"}
    assert inner.calls == []
    assert len(forward_calls) == 1
    rpc_uri, forwarded_command, timeout = forward_calls[0]
    assert rpc_uri == "tcp://leader-address"
    assert timeout == 2.5
    assert forwarded_command.envelope["__forwarded__"] is True
    assert forwarded_command.envelope["name"] == "foo"


def test_returns_leader_unreachable_when_leader_address_unknown(command):
    inner = FakeInnerHandler()

    def forward_fn(rpc_uri, cmd, timeout):
        raise AssertionError("forward_fn should not be called when leader address is unknown")

    handler = LeaderProxyHandler(
        inner=inner,
        elector=FakeElector(leader_id="other"),
        self_id="self",
        resolve_leader_rpc_uri=lambda peer_id: None,
        forward_fn=forward_fn,
        forward_timeout_seconds=1.0,
    )

    result = handler.handle(command)

    assert result.ok is False
    assert result.error_code == 6001
    assert result.error_name == "LEADER_UNREACHABLE"


def test_returns_leader_unreachable_when_forward_fn_fails(command):
    inner = FakeInnerHandler()

    def forward_fn(rpc_uri, cmd, timeout):
        return Err(RuntimeError("connection refused"))

    handler = LeaderProxyHandler(
        inner=inner,
        elector=FakeElector(leader_id="other"),
        self_id="self",
        resolve_leader_rpc_uri=lambda peer_id: "tcp://leader-address",
        forward_fn=forward_fn,
        forward_timeout_seconds=1.0,
    )

    result = handler.handle(command)

    assert result.ok is False
    assert result.error_code == 6001


def test_already_forwarded_command_on_non_leader_is_rejected_without_forwarding_again():
    inner = FakeInnerHandler()

    def forward_fn(rpc_uri, cmd, timeout):
        raise AssertionError("must not forward a second hop")

    handler = LeaderProxyHandler(
        inner=inner,
        elector=FakeElector(leader_id="other"),
        self_id="self",
        resolve_leader_rpc_uri=lambda peer_id: "tcp://leader-address",
        forward_fn=forward_fn,
        forward_timeout_seconds=1.0,
    )

    already_forwarded = Command(
        operation="FUNCTION_REGISTER",
        content_type="application/json",
        envelope={"name": "foo", "__forwarded__": True},
    )
    result = handler.handle(already_forwarded)

    assert result.ok is False
    assert result.error_code == 6001
    assert inner.calls == []
