from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Per-node and per-run status values. A run's own status is the aggregate of
# its nodes': RUNNING while anything is still in flight, COMPLETED only once
# every node reached a terminal state successfully, FAILED if any node
# failed (after exhausting its own retries), CANCELLED if the user stopped it.
PENDING = "pending"
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

# Run-level statuses that make a choreography non-editable and block a new
# run from starting (see ChoreographyRunRepository.has_active_run).
ACTIVE_RUN_STATUSES = frozenset({PENDING, RUNNING})


@dataclass
class NodeRunState:
    """One node's status within one run -- job_id/endpoint_id are set once
    dispatched, not at run-start, since bucket nodes and not-yet-reached
    function nodes have neither."""

    node_id: str
    status: str = PENDING
    job_id: Optional[str] = None
    endpoint_id: Optional[str] = None
    attempt: int = 0
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    duration_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id, "status": self.status, "job_id": self.job_id,
            "endpoint_id": self.endpoint_id, "attempt": self.attempt, "error": self.error,
            "warnings": self.warnings, "duration_ms": self.duration_ms,
        }


@dataclass
class ChoreographyRun:
    """A single execution of a saved Choreography. Deliberately NOT
    event-sourced (see run_choreography.py's orchestrator docstring) -- a
    plain Mongo-backed read/write model, one document per run, so run
    history is just "every doc for this choreography_id" rather than a
    replayed event stream."""

    run_id: str
    choreography_id: str
    status: str = PENDING
    node_states: Dict[str, NodeRunState] = field(default_factory=dict)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "choreography_id": self.choreography_id,
            "status": self.status,
            "node_states": {node_id: ns.to_dict() for node_id, ns in self.node_states.items()},
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
