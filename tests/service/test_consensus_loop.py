from axo_endpoint.core.consensus import (
    BullyLeaderElector,
    DirtyTracker,
    InMemoryReplicatedStateMachine,
)
from axo_endpoint.core.events.in_memory_bus import InMemoryEventBus
from axo_endpoint.core.network.heartbeat import PeerInfo
from axo_endpoint.service.consensus_loop import (
    CONSENSUS_VIEW_CHANGED_EVENT,
    LEADER_ELECTED_EVENT,
    run_consensus_tick,
)


class _FakeHeartbeatSubscriber:
    """Reports one peer whose advertised rpc_uri is a wildcard bind address
    -- exactly what a real node publishes (AXO_ENDPOINT_ROUTER_BIND is
    typically tcp://0.0.0.0:5555, never directly connectable)."""

    def __init__(self, peer_id, wildcard_rpc_uri):
        self._peer = PeerInfo(peer_id=peer_id, service_name="axo-endpoint", rpc_uri=wildcard_rpc_uri)

    def list_peers(self):
        return [self._peer]

    def get_peer(self, peer_id):
        return self._peer if peer_id == self._peer.peer_id else None


def _make_leader(self_id, peer_id, wildcard_rpc_uri):
    elector = BullyLeaderElector(self_id=self_id)
    heartbeat_subscriber = _FakeHeartbeatSubscriber(peer_id, wildcard_rpc_uri)
    dirty_tracker = DirtyTracker(max_dirty_count=1)
    dirty_tracker.mark_function_dirty("fn1:1", b"blob", now=100.0)
    state_machine = InMemoryReplicatedStateMachine()
    return elector, heartbeat_subscriber, dirty_tracker, state_machine


def test_push_target_is_resolved_not_raw_wildcard_address():
    # self_id sorts higher than the peer so this node becomes leader
    # (BullyLeaderElector picks the highest id) -- matches a real deploy
    # where AXO_ENDPOINT_ID is the node's own resolvable hostname.
    elector, heartbeat_subscriber, dirty_tracker, state_machine = _make_leader(
        self_id="node-z", peer_id="node-a", wildcard_rpc_uri="tcp://0.0.0.0:5555",
    )
    pushed = []

    def push_to_peer_fn(rpc_uri, view, member_ids, mutation):
        pushed.append(rpc_uri)

    run_consensus_tick(
        elector=elector,
        heartbeat_subscriber=heartbeat_subscriber,
        dirty_tracker=dirty_tracker,
        state_machine=state_machine,
        self_id="node-z",
        push_to_peer_fn=push_to_peer_fn,
        idle_seconds=0.0,
        now=200.0,
        local_mode=False,
    )

    assert len(pushed) == 1
    # Must be resolved to the peer's own id as hostname, not the raw
    # 0.0.0.0 wildcard the peer's heartbeat advertised -- 0.0.0.0 is never a
    # valid destination for another node to connect to.
    assert pushed[0] == "tcp://node-a:5555"


def test_push_target_uses_localhost_in_local_mode():
    elector, heartbeat_subscriber, dirty_tracker, state_machine = _make_leader(
        self_id="node-z", peer_id="node-a", wildcard_rpc_uri="tcp://0.0.0.0:5555",
    )
    pushed = []

    run_consensus_tick(
        elector=elector,
        heartbeat_subscriber=heartbeat_subscriber,
        dirty_tracker=dirty_tracker,
        state_machine=state_machine,
        self_id="node-z",
        push_to_peer_fn=lambda rpc_uri, *a: pushed.append(rpc_uri),
        idle_seconds=0.0,
        now=200.0,
        local_mode=True,
    )

    assert pushed == ["tcp://localhost:5555"]


def test_emits_leader_elected_and_consensus_view_changed_when_event_bus_supplied():
    # BullyLeaderElector.__init__ optimistically assumes self is leader
    # (term 0, leader_ids={self_id}) before any recompute(). Using a peer_id
    # that sorts *higher* than self_id means the first tick's recompute()
    # picks the peer as winner instead -- a genuine change from the initial
    # view, so both a term bump and a leader->follower role flip fire.
    elector, heartbeat_subscriber, dirty_tracker, state_machine = _make_leader(
        self_id="node-a", peer_id="node-z", wildcard_rpc_uri="tcp://0.0.0.0:5555",
    )
    bus = InMemoryEventBus()
    received = []
    bus.subscribe(LEADER_ELECTED_EVENT, lambda e: received.append(e))
    bus.subscribe(CONSENSUS_VIEW_CHANGED_EVENT, lambda e: received.append(e))

    run_consensus_tick(
        elector=elector,
        heartbeat_subscriber=heartbeat_subscriber,
        dirty_tracker=dirty_tracker,
        state_machine=state_machine,
        self_id="node-a",
        push_to_peer_fn=lambda *a: None,
        idle_seconds=0.0,
        now=200.0,
        event_bus=bus,
    )

    assert len(received) == 2
    event_types = {e.event_type for e in received}
    assert event_types == {LEADER_ELECTED_EVENT, CONSENSUS_VIEW_CHANGED_EVENT}
    leader_elected = next(e for e in received if e.event_type == LEADER_ELECTED_EVENT)
    assert leader_elected.payload["leader_ids"] == ["node-z"]
    view_changed = next(e for e in received if e.event_type == CONSENSUS_VIEW_CHANGED_EVENT)
    assert view_changed.payload["was_leader"] is True
    assert view_changed.payload["is_leader"] is False


def test_no_events_emitted_on_second_tick_with_unchanged_view():
    elector, heartbeat_subscriber, dirty_tracker, state_machine = _make_leader(
        self_id="node-z", peer_id="node-a", wildcard_rpc_uri="tcp://0.0.0.0:5555",
    )
    bus = InMemoryEventBus()
    received = []
    bus.subscribe(LEADER_ELECTED_EVENT, lambda e: received.append(e))
    bus.subscribe(CONSENSUS_VIEW_CHANGED_EVENT, lambda e: received.append(e))

    common_kwargs = dict(
        elector=elector,
        heartbeat_subscriber=heartbeat_subscriber,
        dirty_tracker=dirty_tracker,
        state_machine=state_machine,
        self_id="node-z",
        push_to_peer_fn=lambda *a: None,
        idle_seconds=0.0,
        event_bus=bus,
    )
    run_consensus_tick(now=200.0, **common_kwargs)
    received.clear()
    run_consensus_tick(now=205.0, **common_kwargs)

    assert received == []


def test_does_not_require_event_bus():
    # Default (no event_bus) must keep working exactly as before.
    elector, heartbeat_subscriber, dirty_tracker, state_machine = _make_leader(
        self_id="node-z", peer_id="node-a", wildcard_rpc_uri="tcp://0.0.0.0:5555",
    )
    run_consensus_tick(
        elector=elector,
        heartbeat_subscriber=heartbeat_subscriber,
        dirty_tracker=dirty_tracker,
        state_machine=state_machine,
        self_id="node-z",
        push_to_peer_fn=lambda *a: None,
        idle_seconds=0.0,
        now=200.0,
    )
