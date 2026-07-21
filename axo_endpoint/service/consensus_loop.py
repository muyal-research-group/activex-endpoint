from __future__ import annotations

from typing import Callable, FrozenSet, List, Optional, Tuple, Union

from axo_endpoint.core.consensus.dirty_tracker import DirtyTracker
from axo_endpoint.core.consensus.elector import LeaderElector, LeaderView
from axo_endpoint.core.consensus.membership import ClusterMember
from axo_endpoint.core.consensus.state_machine import ReplicatedStateMachine, StateMutation
from axo_endpoint.core.events.bus import Event as BusEvent, EventBus
from axo_endpoint.core.network.heartbeat import HeartbeatSubscriber
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event
from axo_endpoint.service.transport.address import resolve_peer_address

_Logger = Union[Log, DumbLogger]
PushToPeerFn = Callable[[str, LeaderView, FrozenSet[str], StateMutation], None]

# Bus event_type constants published (if an event_bus is supplied) whenever
# this tick detects a term change / role flip -- consumed by
# ExternalEventForwardingBridge (core/external/bridge.py) to forward
# LeaderElected/ConsensusViewChanged to axo_vem. Distinct from
# log.catalog.Event.Consensus.LEADER_ELECTED, which is a structured-logging
# string, never a bus event_type.
LEADER_ELECTED_EVENT = "LEADER_ELECTED"
CONSENSUS_VIEW_CHANGED_EVENT = "CONSENSUS_VIEW_CHANGED"
# Quorum/degraded events: no such concept exists in BullyLeaderElector itself
# (recompute() unconditionally picks a winner even with zero peers) -- these
# are derived here, purely from observed cluster size tick-over-tick, since
# this is the one place that already computes member_ids every tick. Quorum
# size is a strict majority of the largest cluster size ever observed this
# run (self included), not a configured constant.
CLUSTER_QUORUM_LOST_EVENT = "CLUSTER_QUORUM_LOST"
CLUSTER_QUORUM_RESTORED_EVENT = "CLUSTER_QUORUM_RESTORED"
CLUSTER_DEGRADED_EVENT = "CLUSTER_DEGRADED"


def run_consensus_tick(
    elector: LeaderElector,
    heartbeat_subscriber: HeartbeatSubscriber,
    dirty_tracker: DirtyTracker,
    state_machine: ReplicatedStateMachine,
    self_id: str,
    push_to_peer_fn: PushToPeerFn,
    idle_seconds: float,
    now: float,
    local_mode: bool = False,
    logger: _Logger = None,
    event_bus: Optional[EventBus] = None,
    high_water_mark: int = 0,
    previous_member_ids: Optional[FrozenSet[str]] = None,
) -> Tuple[int, FrozenSet[str]]:
    """One tick of consensus bookkeeping: recompute the leader view from the
    current heartbeat membership, and — if we're leader and replication is
    due — drain the dirty tracker and push the diff to every known peer.

    Called once per existing heartbeat-publish-loop iteration rather than
    from a dedicated thread; the check itself is cheap, so piggybacking on
    that existing cadence avoids a second background loop/config knob.

    A peer's heartbeat-advertised rpc_uri is that peer's own bind address
    (e.g. tcp://0.0.0.0:5555 in any real deployment, not just tcp://127.0.0.1:P
    as in the test harness) -- not itself a connectable destination.
    resolve_peer_address must run on every member before it's usable as a
    push/forward target, exactly like App._resolve_leader_rpc_uri already
    does for leader-proxy forwarding. Skipping this (as this function used
    to) means a push silently "succeeds" locally (the dirty tracker drains)
    while never reaching any real peer over the network.

    ``high_water_mark``/``previous_member_ids`` are this function's only
    cross-tick state, threaded in/out by the caller (App stores them between
    calls) rather than held here, matching this function's existing
    stateless-per-call design (recompute() itself works the same way).
    Returns the updated (high_water_mark, member_ids) pair for the caller to
    pass back in on the next tick.
    """
    logger = logger or DumbLogger()

    members: List[ClusterMember] = [
        ClusterMember(peer_id=p.peer_id, rpc_uri=resolve_peer_address(p.rpc_uri, p.peer_id, local_mode))
        for p in heartbeat_subscriber.list_peers()
    ]
    previous_view = elector.current_view()
    was_leader = self_id in previous_view.leader_ids
    view = elector.recompute(members, now)
    is_leader = self_id in view.leader_ids

    member_ids = frozenset(m.peer_id for m in members) | {self_id}
    new_high_water = max(high_water_mark, len(member_ids))
    if previous_member_ids is not None and event_bus is not None:
        quorum_size_before = (high_water_mark // 2) + 1
        quorum_size_after = (new_high_water // 2) + 1
        had_quorum = len(previous_member_ids) >= quorum_size_before
        has_quorum = len(member_ids) >= quorum_size_after
        if had_quorum and not has_quorum:
            logger.warning_event(
                Event.Consensus.QUORUM_LOST,
                component=Component.CONSENSUS,
                member_count=len(member_ids),
                quorum_size=quorum_size_after,
            )
            event_bus.emit(BusEvent(
                event_type=CLUSTER_QUORUM_LOST_EVENT,
                payload={"term": view.term, "member_count": len(member_ids), "quorum_size": quorum_size_after},
                timestamp=now,
            ))
        elif not had_quorum and has_quorum:
            logger.info_event(
                Event.Consensus.QUORUM_RESTORED,
                component=Component.CONSENSUS,
                member_count=len(member_ids),
                quorum_size=quorum_size_after,
            )
            event_bus.emit(BusEvent(
                event_type=CLUSTER_QUORUM_RESTORED_EVENT,
                payload={"term": view.term, "member_count": len(member_ids), "quorum_size": quorum_size_after},
                timestamp=now,
            ))
        elif has_quorum:
            for evicted_peer_id in previous_member_ids - member_ids:
                logger.info_event(
                    Event.Consensus.DEGRADED,
                    component=Component.CONSENSUS,
                    member_count=len(member_ids),
                    quorum_size=quorum_size_after,
                    evicted_peer_id=evicted_peer_id,
                )
                event_bus.emit(BusEvent(
                    event_type=CLUSTER_DEGRADED_EVENT,
                    payload={
                        "term": view.term, "member_count": len(member_ids), "quorum_size": quorum_size_after,
                        "evicted_peer_id": evicted_peer_id,
                    },
                    timestamp=now,
                ))

    if view.term != previous_view.term:
        logger.info_event(
            Event.Consensus.LEADER_ELECTED,
            component=Component.CONSENSUS,
            leader_ids=list(view.leader_ids),
            term=view.term,
        )
        if was_leader and not is_leader:
            logger.info_event(
                Event.Consensus.STEPPED_DOWN,
                component=Component.CONSENSUS,
                new_leader_ids=list(view.leader_ids),
                term=view.term,
            )
        if event_bus is not None:
            event_bus.emit(BusEvent(
                event_type=LEADER_ELECTED_EVENT,
                payload={"leader_ids": list(view.leader_ids), "term": view.term},
                timestamp=now,
            ))

    if event_bus is not None and was_leader != is_leader:
        event_bus.emit(BusEvent(
            event_type=CONSENSUS_VIEW_CHANGED_EVENT,
            payload={
                "term": view.term,
                "was_leader": was_leader,
                "is_leader": is_leader,
                "leader_ids": list(view.leader_ids),
            },
            timestamp=now,
        ))

    logger.debug_event(
        Event.Consensus.TICK,
        component=Component.CONSENSUS,
        role="leader" if is_leader else "follower",
        term=view.term,
        leader_ids=list(view.leader_ids),
        member_count=len(members),
        dirty_pending=dirty_tracker.pending_count(),
    )

    if not is_leader:
        return new_high_water, member_ids

    if not dirty_tracker.should_flush(now, idle_seconds):
        return new_high_water, member_ids

    mutation = dirty_tracker.drain()
    state_machine.apply_local(mutation)
    if not mutation.function_changes and not mutation.data_changes and not mutation.bucket_changes:
        return new_high_water, member_ids

    logger.info_event(
        Event.Consensus.REPLICATION_FLUSHED,
        component=Component.CONSENSUS,
        function_count=len(mutation.function_changes),
        data_count=len(mutation.data_changes),
        bucket_count=len(mutation.bucket_changes),
        term=view.term,
    )
    for member in members:
        push_to_peer_fn(member.rpc_uri, view, member_ids, mutation)

    return new_high_water, member_ids
