from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from axo_vem.domain.events.models import ChoreographyGraph


@dataclass(frozen=True)
class ConcurrencyViolation:
    node_id: str
    function_id: str
    required_concurrency: int
    max_concurrency: int


def check_concurrency(
    graph: ChoreographyGraph, max_concurrency_by_function: Dict[str, int],
) -> List[ConcurrencyViolation]:
    """For every function node, sums how many concurrent invocations it
    would face in the same wave -- duplicate fn_to_fn edges landing on it,
    plus any bucket_to_fn edge's configured parallelism -- and flags
    anything exceeding that function's declared max_concurrency. Pure, no
    I/O: max_concurrency_by_function is looked up by the caller from
    whatever cached function metadata it already has (axo_vem's function
    read-model already carries runtime_spec, populated passively via the
    FUNCTION_REGISTERED/FUNCTION_UPDATED external events every node
    forwards -- no new wire op needed just for this static cap).

    This is a design-time check only: it has no visibility into jobs
    running outside this choreography (no wire op exposes the cluster's
    live in-flight count), so it can't catch a function also being
    hammered manually via the ordinary run page at the same time -- an
    accepted limitation, not a bug to fix here."""
    violations: List[ConcurrencyViolation] = []

    for node in graph.nodes:
        if node.kind != "function" or not node.function_id:
            continue

        concurrency = 0
        for edge in graph.edges:
            if edge.target_node_id != node.node_id:
                continue
            if edge.kind == "fn_to_fn":
                concurrency += 1
            elif edge.kind == "bucket_to_fn":
                concurrency += max(1, edge.parallelism)
        concurrency = max(concurrency, 1)  # a node with no inbound edges still runs once

        max_allowed = max_concurrency_by_function.get(node.function_id, 1)
        if concurrency > max_allowed:
            violations.append(ConcurrencyViolation(
                node_id=node.node_id, function_id=node.function_id,
                required_concurrency=concurrency, max_concurrency=max_allowed,
            ))
    return violations
