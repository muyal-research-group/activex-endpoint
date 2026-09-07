from axo_vem.domain.choreography.concurrency_check import check_concurrency
from axo_vem.domain.events.models import ChoreographyEdge, ChoreographyGraph, ChoreographyNode


def _fn_node(node_id, function_id):
    return ChoreographyNode(
        node_id=node_id, kind="function", position={"x": 0.0, "y": 0.0}, function_id=function_id,
    )


def _bucket_node(node_id):
    return ChoreographyNode(node_id=node_id, kind="bucket", position={"x": 0.0, "y": 0.0}, bucket_name="bk")


def test_no_violation_for_a_single_invocation():
    graph = ChoreographyGraph(nodes=[_fn_node("a", "fn1")], edges=[])
    assert check_concurrency(graph, {"fn1": 1}) == []


def test_duplicate_fan_out_edges_within_capacity_is_fine():
    graph = ChoreographyGraph(
        nodes=[_fn_node("a", "fn-a"), _fn_node("b", "fn-b")],
        edges=[
            ChoreographyEdge(edge_id="e1", source_node_id="a", target_node_id="b", kind="fn_to_fn"),
            ChoreographyEdge(edge_id="e2", source_node_id="a", target_node_id="b", kind="fn_to_fn"),
        ],
    )
    assert check_concurrency(graph, {"fn-a": 1, "fn-b": 2}) == []


def test_duplicate_fan_out_edges_exceeding_capacity_is_flagged():
    graph = ChoreographyGraph(
        nodes=[_fn_node("a", "fn-a"), _fn_node("b", "fn-b")],
        edges=[
            ChoreographyEdge(edge_id="e1", source_node_id="a", target_node_id="b", kind="fn_to_fn"),
            ChoreographyEdge(edge_id="e2", source_node_id="a", target_node_id="b", kind="fn_to_fn"),
            ChoreographyEdge(edge_id="e3", source_node_id="a", target_node_id="b", kind="fn_to_fn"),
        ],
    )
    violations = check_concurrency(graph, {"fn-a": 1, "fn-b": 2})
    assert len(violations) == 1
    assert violations[0].node_id == "b"
    assert violations[0].required_concurrency == 3
    assert violations[0].max_concurrency == 2


def test_bucket_edge_parallelism_within_capacity_is_fine():
    graph = ChoreographyGraph(
        nodes=[_bucket_node("bk"), _fn_node("b", "fn-b")],
        edges=[ChoreographyEdge(edge_id="e1", source_node_id="bk", target_node_id="b", kind="bucket_to_fn", parallelism=2)],
    )
    assert check_concurrency(graph, {"fn-b": 2}) == []


def test_bucket_edge_parallelism_exceeding_capacity_is_flagged():
    graph = ChoreographyGraph(
        nodes=[_bucket_node("bk"), _fn_node("b", "fn-b")],
        edges=[ChoreographyEdge(edge_id="e1", source_node_id="bk", target_node_id="b", kind="bucket_to_fn", parallelism=5)],
    )
    violations = check_concurrency(graph, {"fn-b": 2})
    assert len(violations) == 1
    assert violations[0].required_concurrency == 5


def test_default_max_concurrency_is_one_when_function_unknown():
    graph = ChoreographyGraph(
        nodes=[_fn_node("a", "fn-a"), _fn_node("b", "fn-unknown")],
        edges=[
            ChoreographyEdge(edge_id="e1", source_node_id="a", target_node_id="b", kind="fn_to_fn"),
            ChoreographyEdge(edge_id="e2", source_node_id="a", target_node_id="b", kind="fn_to_fn"),
        ],
    )
    violations = check_concurrency(graph, {"fn-a": 1})
    assert len(violations) == 1
    assert violations[0].max_concurrency == 1
