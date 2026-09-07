import time

import cloudpickle
import zmq

from axo_shared.protocol import Command
from axo_shared import wire
from tests.service.consensus._cluster import spin_up_node, wait_until


def _send_command(rpc_uri, command, timeout_ms=3000):
    dealer = zmq.Context.instance().socket(zmq.DEALER)
    dealer.setsockopt(zmq.RCVTIMEO, timeout_ms)
    dealer.connect(rpc_uri)
    try:
        dealer.send_multipart(wire.encode_command(command))
        frames = dealer.recv_multipart()
        return wire.decode_command_result(frames).unwrap()
    finally:
        dealer.close()


def _register_command(name, code=b"code"):
    return Command(
        operation=wire.FUNCTION_REGISTER,
        content_type="application/octet-stream",
        envelope={"function_id": name, "name": name},
        payload=code,
    )


def _register_and_upload_data(rpc_uri, name, version=1, data=b"data-bytes", chunk_bytes=4, format="raw", kind="fs"):
    """Drives the full client-facing chunked protocol against ``rpc_uri``
    (leader or follower -- DATA_REGISTER is transparently proxied either
    way): register the metadata, then push every chunk directly to whichever
    node the registration response names as leader (DATA_CHUNK_PUT is never
    proxied). Returns the final chunk's CommandResult."""
    register_result = _send_command(rpc_uri, Command(
        operation=wire.DATA_REGISTER,
        content_type="application/json",
        envelope={
            "name": name, "version": version, "format": format, "kind": kind,
            "total_size": len(data), "chunk_bytes": chunk_bytes,
        },
    ))
    if not register_result.ok:
        return register_result

    leader_rpc_uri = register_result.metadata["leader_rpc_uri"]
    total_chunks = register_result.metadata["total_chunks"]
    result = register_result
    for i in range(total_chunks):
        chunk = data[i * chunk_bytes:(i + 1) * chunk_bytes]
        result = _send_command(leader_rpc_uri, Command(
            operation=wire.DATA_CHUNK_PUT,
            content_type="application/octet-stream",
            envelope={"name": name, "version": version, "chunk_index": i},
            payload=chunk,
        ))
    return result


def _register_function_command(name, fn):
    return Command(
        operation=wire.FUNCTION_REGISTER,
        content_type="application/octet-stream",
        envelope={"function_id": name, "name": name},
        payload=cloudpickle.dumps(fn),
    )


def _stream_write_fn(params, ctx):
    from axo_endpoint import dataio

    ref = dataio.write_chunks(params["name"], params["version"], [b"ab", b"cd", b"ef"], chunk_bytes=2)
    return {"kind": ref.kind, "location": ref.location}


def _leader_and_follower(nodes):
    leader = next(n for n in nodes if n.elector.is_leader(n.config.AXO_ENDPOINT_ID))
    follower = next(n for n in nodes if n is not leader)
    return leader, follower


def _two_node_cluster(tmp_path, monkeypatch, **env_overrides):
    node1 = spin_up_node(tmp_path, monkeypatch, "node-a", **env_overrides)
    node2 = spin_up_node(
        tmp_path, monkeypatch, "node-b", sub_connect=[node1.config.AXO_ENDPOINT_PUB_BIND], **env_overrides
    )
    nodes = [node1, node2]
    assert wait_until(
        lambda: all(n.elector.current_view().leader_ids == frozenset({"node-b"}) for n in nodes),
        timeout=10.0,
    )
    return nodes


def test_function_registered_on_leader_appears_on_follower_after_idle_threshold(tmp_path, clean_env, monkeypatch):
    nodes = _two_node_cluster(tmp_path, monkeypatch)
    try:
        leader, follower = _leader_and_follower(nodes)

        result = _send_command(leader.config.AXO_ENDPOINT_ROUTER_BIND, _register_command("foo"))
        assert result.ok is True

        assert wait_until(
            lambda: follower.functions_store.get_by_id("foo").unwrap() is not None, timeout=5.0
        )
        record = follower.functions_store.get_by_id("foo").unwrap()
        assert record.code == b"code"
    finally:
        for n in nodes:
            n.stop()


def test_register_against_follower_succeeds_transparently(tmp_path, clean_env, monkeypatch):
    nodes = _two_node_cluster(tmp_path, monkeypatch)
    try:
        leader, follower = _leader_and_follower(nodes)

        result = _send_command(follower.config.AXO_ENDPOINT_ROUTER_BIND, _register_command("bar"))

        # The client never sees a "not leader" error -- it gets back exactly
        # what registering against the leader directly would have returned.
        assert result.ok is True
        assert result.metadata == {"function_id": "bar", "version": 1}
        assert leader.functions_store.get_by_id("bar").unwrap() is not None
    finally:
        for n in nodes:
            n.stop()


def test_max_dirty_count_flush_fires_before_idle_timeout_under_burst_load(tmp_path, clean_env, monkeypatch):
    nodes = _two_node_cluster(
        tmp_path,
        monkeypatch,
        AXO_ENDPOINT_CONSENSUS_REPLICATION_MAX_DIRTY="3",
        AXO_ENDPOINT_CONSENSUS_REPLICATION_IDLE_SECONDS="30.0",
    )
    try:
        leader, follower = _leader_and_follower(nodes)

        for i in range(3):
            result = _send_command(leader.config.AXO_ENDPOINT_ROUTER_BIND, _register_command(f"burst{i}"))
            assert result.ok is True

        # Bounded well under the 30s idle timeout -- only explainable by
        # MAX_DIRTY firing before the idle window would have.
        assert wait_until(
            lambda: all(
                follower.functions_store.get_by_id(f"burst{i}").unwrap() is not None for i in range(3)
            ),
            timeout=5.0,
        )
    finally:
        for n in nodes:
            n.stop()


def test_data_only_registration_replicates_catalog_to_follower(tmp_path, clean_env, monkeypatch):
    # No FUNCTION_REGISTER happens in this test at all -- a flush window with
    # only data_changes pending, no function_changes. This is the regression
    # guard for two bugs found while building the data domain: (1) DataRegistry
    # emitting its event under the same string FunctionState.REGISTERED.value
    # uses would make RegistrySyncBridge.on_function_event fire and crash on a
    # missing "function_id" key; (2) run_consensus_tick's flush gate used to
    # only check function_changes, so a data-only flush would never be pushed
    # to peers at all. Both are fixed; this proves it end-to-end across real
    # nodes rather than just at the unit level.
    nodes = _two_node_cluster(tmp_path, monkeypatch)
    try:
        leader, follower = _leader_and_follower(nodes)

        result = _register_and_upload_data(leader.config.AXO_ENDPOINT_ROUTER_BIND, "df1", data=b"data-bytes", chunk_bytes=4)
        assert result.ok is True
        assert result.metadata["complete"] is True

        assert wait_until(
            lambda: follower.data_store.get_by_id("df1").unwrap() is not None, timeout=5.0
        )
        record = follower.data_store.get_by_id("df1").unwrap()
        assert record.kind == "fs"
        assert record.total_chunks == 3

        # The catalog entry replicates via the metadata-sync path (above);
        # the actual chunk bytes replicate separately via the diff-based
        # blob-replication background loop, using the leader's own
        # DataRegistry to reconstruct -- confirm they eventually land on the
        # follower's own local storage too, proving both channels cooperate
        # end-to-end across real nodes.
        assert wait_until(
            lambda: follower.data_registry.status("df1", 1).complete, timeout=5.0,
        )
        assert follower.data_registry.read_whole("df1", 1).unwrap() == b"data-bytes"
    finally:
        for n in nodes:
            n.stop()


def test_data_register_against_follower_succeeds_transparently(tmp_path, clean_env, monkeypatch):
    nodes = _two_node_cluster(tmp_path, monkeypatch)
    try:
        leader, follower = _leader_and_follower(nodes)

        result = _register_and_upload_data(follower.config.AXO_ENDPOINT_ROUTER_BIND, "df2", data=b"data-bytes", chunk_bytes=4)

        assert result.ok is True
        assert result.metadata["data_id"] == "df2"
        assert leader.data_store.get_by_id("df2").unwrap() is not None
    finally:
        for n in nodes:
            n.stop()


def test_incomplete_dataset_on_leader_never_replicates_to_follower(tmp_path, clean_env, monkeypatch):
    nodes = _two_node_cluster(tmp_path, monkeypatch)
    try:
        leader, follower = _leader_and_follower(nodes)

        register_result = _send_command(leader.config.AXO_ENDPOINT_ROUTER_BIND, Command(
            operation=wire.DATA_REGISTER,
            content_type="application/json",
            envelope={
                "name": "partial1", "version": 1, "format": "raw", "kind": "fs",
                "total_size": 8, "chunk_bytes": 4,
            },
        ))
        assert register_result.ok is True
        leader_rpc_uri = register_result.metadata["leader_rpc_uri"]

        # Only push chunk 0 of 2 -- the leader itself never becomes complete.
        chunk_result = _send_command(leader_rpc_uri, Command(
            operation=wire.DATA_CHUNK_PUT,
            content_type="application/octet-stream",
            envelope={"name": "partial1", "version": 1, "chunk_index": 0},
            payload=b"abcd",
        ))
        assert chunk_result.ok is True
        assert chunk_result.metadata["complete"] is False

        # Give the replication loop several ticks' worth of time to (not) act.
        time.sleep(1.0)

        follower_status = follower.data_registry.status("partial1", 1)
        assert follower_status.present_chunk_indices == []
    finally:
        for n in nodes:
            n.stop()


def test_function_stream_write_replicates_to_follower(tmp_path, clean_env, monkeypatch):
    nodes = _two_node_cluster(tmp_path, monkeypatch)
    try:
        leader, follower = _leader_and_follower(nodes)

        reg_result = _send_command(
            leader.config.AXO_ENDPOINT_ROUTER_BIND, _register_function_command("stream_writer", _stream_write_fn),
        )
        assert reg_result.ok is True

        submit_result = _send_command(leader.config.AXO_ENDPOINT_ROUTER_BIND, Command(
            operation=wire.JOB_SUBMIT,
            content_type="application/json",
            envelope={
                "function_id": "stream_writer", "function_name": "stream_writer", "function_version": 1,
                "params": {"name": "streamed1", "version": 1},
            },
        ))
        assert submit_result.ok is True
        job_id = submit_result.metadata["job_id"]

        def _job_completed():
            r = _send_command(leader.config.AXO_ENDPOINT_ROUTER_BIND, Command(
                operation=wire.JOB_RESULT, content_type="application/json", envelope={"job_id": job_id},
            ))
            return r.ok and r.metadata.get("status") == "COMPLETED"

        assert wait_until(_job_completed, timeout=5.0)

        # The stream-written output must show up on the follower via the
        # same diff-based replication loop a client upload uses -- proving
        # register-at-finalize (not register-then-stream) integrates
        # cleanly with the leader-completeness-gated replication path.
        assert wait_until(
            lambda: follower.data_registry.status("streamed1", 1).complete, timeout=5.0,
        )
        assert follower.data_registry.read_whole("streamed1", 1).unwrap() == b"abcdef"
    finally:
        for n in nodes:
            n.stop()


def test_late_joining_node_catches_up_via_state_sync_pull(tmp_path, clean_env, monkeypatch):
    nodes = _two_node_cluster(tmp_path, monkeypatch)
    try:
        leader, follower = _leader_and_follower(nodes)
        result = _send_command(leader.config.AXO_ENDPOINT_ROUTER_BIND, _register_command("early"))
        assert result.ok is True
        assert wait_until(lambda: follower.functions_store.get_by_id("early").unwrap() is not None, timeout=5.0)

        # "node-0" sorts below both existing ids, so it never disturbs the
        # existing leader belief -- this isolates the assertion to the
        # one-shot STATE_SYNC_PULL catch-up path. It connects only to the
        # follower (never the leader), so the only way it can learn about
        # "early" is by pulling the follower's already-replicated state.
        late_node = spin_up_node(
            tmp_path, monkeypatch, "node-0", sub_connect=[follower.config.AXO_ENDPOINT_PUB_BIND]
        )
        nodes.append(late_node)

        assert wait_until(
            lambda: late_node.functions_store.get_by_id("early").unwrap() is not None, timeout=5.0
        )
    finally:
        for n in nodes:
            n.stop()
