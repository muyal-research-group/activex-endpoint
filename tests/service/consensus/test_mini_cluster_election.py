from tests.service.consensus._cluster import spin_up_node, wait_until


def test_three_node_cluster_converges_on_exactly_one_leader(tmp_path, clean_env, monkeypatch):
    node1 = spin_up_node(tmp_path, monkeypatch, "node-a")
    node2 = spin_up_node(
        tmp_path, monkeypatch, "node-b", sub_connect=[node1.config.AXO_ENDPOINT_PUB_BIND]
    )
    node3 = spin_up_node(
        tmp_path,
        monkeypatch,
        "node-c",
        sub_connect=[node1.config.AXO_ENDPOINT_PUB_BIND, node2.config.AXO_ENDPOINT_PUB_BIND],
    )
    nodes = [node1, node2, node3]

    try:
        expected_leader = max(n.config.AXO_ENDPOINT_ID for n in nodes)

        def all_converged() -> bool:
            views = [n.elector.current_view().leader_ids for n in nodes]
            return all(v == frozenset({expected_leader}) for v in views)

        assert wait_until(all_converged, timeout=10.0), [
            (n.config.AXO_ENDPOINT_ID, n.elector.current_view()) for n in nodes
        ]

        leaders = [n for n in nodes if n.elector.is_leader(n.config.AXO_ENDPOINT_ID)]
        assert len(leaders) == 1
        assert leaders[0].config.AXO_ENDPOINT_ID == expected_leader
    finally:
        for n in nodes:
            n.stop()


def test_killing_the_leader_triggers_reelection_among_survivors(tmp_path, clean_env, monkeypatch):
    node1 = spin_up_node(tmp_path, monkeypatch, "node-a")
    node2 = spin_up_node(
        tmp_path, monkeypatch, "node-b", sub_connect=[node1.config.AXO_ENDPOINT_PUB_BIND]
    )
    node3 = spin_up_node(
        tmp_path,
        monkeypatch,
        "node-c",
        sub_connect=[node1.config.AXO_ENDPOINT_PUB_BIND, node2.config.AXO_ENDPOINT_PUB_BIND],
    )
    nodes = {n.config.AXO_ENDPOINT_ID: n for n in [node1, node2, node3]}
    survivors = [node1, node2]  # node-c (highest id) will be stopped below

    try:
        # node-c has the highest id, so it's the initial leader.
        def first_leader_elected() -> bool:
            return all(n.elector.current_view().leader_ids == frozenset({"node-c"}) for n in nodes.values())

        assert wait_until(first_leader_elected, timeout=10.0)
        initial_term = nodes["node-c"].elector.current_view().term

        nodes["node-c"].stop()

        def reelected_among_survivors() -> bool:
            views = [n.elector.current_view() for n in survivors]
            return all(
                v.leader_ids == frozenset({"node-b"}) and v.term > initial_term for v in views
            )

        assert wait_until(reelected_among_survivors, timeout=10.0), [
            (n.config.AXO_ENDPOINT_ID, n.elector.current_view()) for n in survivors
        ]
    finally:
        for n in survivors:
            n.stop()
