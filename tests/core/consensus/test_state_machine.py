from axo_endpoint.core.consensus.elector import LeaderView
from axo_endpoint.core.consensus.state_machine import (
    ClusterState,
    InMemoryReplicatedStateMachine,
    StateMutation,
    decode_bucket_changes,
    decode_cluster_state,
    decode_data_changes,
    decode_function_changes,
    decode_state_changes,
    encode_bucket_changes,
    encode_cluster_state,
    encode_data_changes,
    encode_function_changes,
    encode_state_changes,
)


def test_apply_local_marks_dirty_and_snapshot_reflects_it():
    machine = InMemoryReplicatedStateMachine()
    machine.apply_local(StateMutation(function_changes={"foo:1": b'{"name": "foo"}'}))

    snapshot = machine.snapshot()
    assert snapshot.functions == {"foo:1": b'{"name": "foo"}'}
    assert snapshot.version == 1


def test_apply_local_updates_leader_view():
    machine = InMemoryReplicatedStateMachine()
    view = LeaderView(leader_ids=frozenset({"a"}), term=3, decided_at=1.0)
    machine.apply_local(StateMutation(leader_view=view))

    snapshot = machine.snapshot()
    assert snapshot.leader_ids == frozenset({"a"})
    assert snapshot.term == 3


def test_apply_remote_with_higher_version_overwrites_and_returns_true():
    machine = InMemoryReplicatedStateMachine()
    incoming = ClusterState(term=1, leader_ids=frozenset({"x"}), functions={"foo:1": b"blob"}, version=5)
    assert machine.apply_remote(incoming) is True
    assert machine.snapshot() == incoming


def test_apply_remote_with_stale_version_is_ignored_and_returns_false():
    machine = InMemoryReplicatedStateMachine()
    machine.apply_remote(ClusterState(version=5))
    stale = ClusterState(term=1, leader_ids=frozenset({"x"}), functions={"foo:1": b"blob"}, version=5)
    assert machine.apply_remote(stale) is False
    assert machine.snapshot().functions == {}


def test_encode_decode_function_changes_round_trip():
    changes = {"foo:1": b'{"name": "foo", "version": 1}'}
    payload = encode_function_changes(changes)
    assert decode_function_changes(payload) == changes


def test_decode_function_changes_of_empty_payload_is_empty_dict():
    assert decode_function_changes(b"") == {}


def test_encode_decode_cluster_state_round_trip():
    state = ClusterState(
        term=2,
        leader_ids=frozenset({"a"}),
        members=frozenset({"a", "b"}),
        functions={"foo:1": b'{"name": "foo", "version": 1}'},
        data={"bar:1": b'{"name": "bar", "version": 1}'},
        buckets={"mybucket": b'{"name": "mybucket", "quota_bytes": 1024, "created_at": 0.0}'},
        version=7,
    )
    assert decode_cluster_state(encode_cluster_state(state)) == state


def test_apply_local_marks_data_dirty_and_snapshot_reflects_it():
    machine = InMemoryReplicatedStateMachine()
    machine.apply_local(StateMutation(data_changes={"bar:1": b'{"name": "bar"}'}))

    snapshot = machine.snapshot()
    assert snapshot.data == {"bar:1": b'{"name": "bar"}'}
    assert snapshot.version == 1


def test_encode_decode_data_changes_round_trip():
    changes = {"bar:1": b'{"name": "bar", "version": 1}'}
    payload = encode_data_changes(changes)
    assert decode_data_changes(payload) == changes


def test_decode_data_changes_of_empty_payload_is_empty_dict():
    assert decode_data_changes(b"") == {}


def test_apply_local_marks_bucket_dirty_and_snapshot_reflects_it():
    machine = InMemoryReplicatedStateMachine()
    machine.apply_local(StateMutation(bucket_changes={"mybucket": b'{"name": "mybucket"}'}))

    snapshot = machine.snapshot()
    assert snapshot.buckets == {"mybucket": b'{"name": "mybucket"}'}
    assert snapshot.version == 1


def test_encode_decode_bucket_changes_round_trip():
    changes = {"mybucket": b'{"name": "mybucket", "quota_bytes": 1024, "created_at": 0.0}'}
    payload = encode_bucket_changes(changes)
    assert decode_bucket_changes(payload) == changes


def test_decode_bucket_changes_of_empty_payload_is_empty_dict():
    assert decode_bucket_changes(b"") == {}


def test_encode_decode_state_changes_round_trip_all_domains():
    function_changes = {"foo:1": b'{"name": "foo", "version": 1}'}
    data_changes = {"bar:1": b'{"name": "bar", "version": 1}'}
    bucket_changes = {"mybucket": b'{"name": "mybucket", "quota_bytes": 1024, "created_at": 0.0}'}
    payload = encode_state_changes(function_changes, data_changes, bucket_changes)
    assert decode_state_changes(payload) == (function_changes, data_changes, bucket_changes)


def test_decode_state_changes_of_empty_payload_is_three_empty_dicts():
    assert decode_state_changes(b"") == ({}, {}, {})
