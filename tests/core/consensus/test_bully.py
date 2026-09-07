from axo_endpoint.core.consensus.bully import BullyLeaderElector
from axo_endpoint.core.consensus.membership import ClusterMember


def test_single_node_is_its_own_leader():
    elector = BullyLeaderElector(self_id="a")
    view = elector.recompute([], now=1.0)
    assert view.leader_ids == frozenset({"a"})
    assert elector.is_leader("a") is True


def test_highest_id_among_members_wins():
    elector = BullyLeaderElector(self_id="b")
    members = [ClusterMember(peer_id="a", rpc_uri="tcp://a"), ClusterMember(peer_id="c", rpc_uri="tcp://c")]
    view = elector.recompute(members, now=1.0)
    assert view.leader_ids == frozenset({"c"})
    assert elector.is_leader("c") is True
    assert elector.is_leader("b") is False


def test_term_increments_only_when_leader_actually_changes():
    elector = BullyLeaderElector(self_id="b")
    members = [ClusterMember(peer_id="a", rpc_uri="tcp://a"), ClusterMember(peer_id="c", rpc_uri="tcp://c")]

    first = elector.recompute(members, now=1.0)
    second = elector.recompute(members, now=2.0)
    assert second.term == first.term

    members_without_c = [ClusterMember(peer_id="a", rpc_uri="tcp://a")]
    third = elector.recompute(members_without_c, now=3.0)
    assert third.leader_ids == frozenset({"b"})
    assert third.term == first.term + 1


def test_leader_set_size_is_one():
    elector = BullyLeaderElector(self_id="a")
    assert elector.leader_set_size == 1
