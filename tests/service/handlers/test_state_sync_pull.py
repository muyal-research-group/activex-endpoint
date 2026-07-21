import pytest

from axo_endpoint.core.consensus.state_machine import ClusterState, InMemoryReplicatedStateMachine, decode_cluster_state
from axo_shared.protocol import Command
from axo_endpoint.service.handlers.state_sync_pull import StateSyncPullHandler


@pytest.fixture
def state_machine():
    machine = InMemoryReplicatedStateMachine()
    machine.apply_remote(
        ClusterState(
            term=3,
            leader_ids=frozenset({"leader"}),
            members=frozenset({"leader", "self"}),
            functions={"foo:1": b'{"name": "foo"}'},
            data={"bar:1": b'{"name": "bar"}'},
            version=1,
        )
    )
    return machine


def test_pull_returns_current_snapshot(state_machine):
    handler = StateSyncPullHandler(state_machine=state_machine)

    result = handler.handle(Command(operation="STATE_SYNC_PULL", content_type="application/json", envelope={}))

    assert result.ok is True
    decoded = decode_cluster_state(result.payload)
    assert decoded == state_machine.snapshot()
    assert decoded.data == {"bar:1": b'{"name": "bar"}'}
