from __future__ import annotations

from typing import Dict, List, Set

from axo_vem.domain.events.models import ChoreographyGraph


def dependencies_of(graph: ChoreographyGraph) -> Dict[str, Set[str]]:
    """node_id -> the set of node_ids that must complete before it can start."""
    deps: Dict[str, Set[str]] = {n.node_id: set() for n in graph.nodes}
    for edge in graph.edges:
        deps.setdefault(edge.target_node_id, set()).add(edge.source_node_id)
    return deps


def dependents_of(graph: ChoreographyGraph) -> Dict[str, Set[str]]:
    """node_id -> the set of node_ids that depend directly on it."""
    dependents: Dict[str, Set[str]] = {n.node_id: set() for n in graph.nodes}
    for edge in graph.edges:
        dependents.setdefault(edge.source_node_id, set()).add(edge.target_node_id)
    return dependents


def topological_waves(graph: ChoreographyGraph) -> List[List[str]]:
    """Groups node ids into ordered waves: everything in wave N has all its
    dependencies satisfied by the end of wave N-1, and nothing in a wave
    depends on anything else in that same wave -- the orchestrator can
    dispatch every node in one wave concurrently. Bucket nodes participate
    like any other node (a mid-chain A -> BK1 -> C means C's wave doesn't
    start until BK1's completes). Raises ValueError on a cycle."""
    remaining = dependencies_of(graph)
    waves: List[List[str]] = []
    done: Set[str] = set()

    while remaining:
        ready = [node_id for node_id, deps in remaining.items() if deps <= done]
        if not ready:
            raise ValueError(f"choreography graph has a cycle among: {sorted(remaining)}")
        waves.append(sorted(ready))
        done.update(ready)
        for node_id in ready:
            del remaining[node_id]
    return waves


def downstream_of(graph: ChoreographyGraph, node_id: str) -> Set[str]:
    """Every node transitively dependent on node_id. Every edge is a hard
    prerequisite here (no OR-joins) -- a node reachable forward from a
    failed node can never proceed regardless of its other dependencies, so
    this is a plain forward-reachability walk, not a "does it have a
    surviving alternate path" check."""
    dependents = dependents_of(graph)
    affected: Set[str] = set()
    frontier = list(dependents.get(node_id, set()))
    while frontier:
        current = frontier.pop()
        if current in affected:
            continue
        affected.add(current)
        frontier.extend(dependents.get(current, set()))
    return affected
