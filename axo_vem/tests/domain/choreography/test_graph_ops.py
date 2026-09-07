import pytest

from axo_vem.domain.choreography.graph_ops import downstream_of, topological_waves
from axo_vem.domain.events.models import ChoreographyEdge, ChoreographyGraph, ChoreographyNode


def _node(node_id, kind="function"):
    return ChoreographyNode(node_id=node_id, kind=kind, position={"x": 0.0, "y": 0.0})


def _edge(edge_id, source, target, kind="fn_to_fn"):
    return ChoreographyEdge(edge_id=edge_id, source_node_id=source, target_node_id=target, kind=kind)


def test_single_node_no_edges_is_one_wave():
    graph = ChoreographyGraph(nodes=[_node("a")], edges=[])
    assert topological_waves(graph) == [["a"]]


def test_linear_chain_is_one_node_per_wave():
    graph = ChoreographyGraph(
        nodes=[_node("a"), _node("b"), _node("c")],
        edges=[_edge("e1", "a", "b"), _edge("e2", "b", "c")],
    )
    assert topological_waves(graph) == [["a"], ["b"], ["c"]]


def test_fan_out_to_same_wave():
    graph = ChoreographyGraph(
        nodes=[_node("a"), _node("b1"), _node("b2")],
        edges=[_edge("e1", "a", "b1"), _edge("e2", "a", "b2")],
    )
    assert topological_waves(graph) == [["a"], ["b1", "b2"]]


def test_independent_branches_can_land_in_the_same_wave():
    graph = ChoreographyGraph(nodes=[_node("a"), _node("b")], edges=[])
    assert topological_waves(graph) == [["a", "b"]]


def test_cycle_raises_value_error():
    graph = ChoreographyGraph(
        nodes=[_node("a"), _node("b")],
        edges=[_edge("e1", "a", "b"), _edge("e2", "b", "a")],
    )
    with pytest.raises(ValueError):
        topological_waves(graph)


def test_downstream_of_covers_transitive_dependents():
    graph = ChoreographyGraph(
        nodes=[_node("a"), _node("b"), _node("c"), _node("d")],
        edges=[_edge("e1", "a", "b"), _edge("e2", "b", "c")],
    )
    assert downstream_of(graph, "a") == {"b", "c"}
    assert downstream_of(graph, "b") == {"c"}
    assert downstream_of(graph, "d") == set()


def test_downstream_of_excludes_independent_branches():
    """A fails -> only its own dependents are affected; an unrelated branch
    (c, with no edge from a) keeps running."""
    graph = ChoreographyGraph(
        nodes=[_node("a"), _node("b"), _node("c")],
        edges=[_edge("e1", "a", "b")],
    )
    assert downstream_of(graph, "a") == {"b"}
    assert "c" not in downstream_of(graph, "a")
