from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import FrozenSet, List

from axo_endpoint.core.consensus.membership import ClusterMember


@dataclass(frozen=True)
class LeaderView:
    """One consensus round's outcome: who leads, for how long, as of when."""

    leader_ids: FrozenSet[str] = field(default_factory=frozenset)
    term: int = 0
    decided_at: float = 0.0


class LeaderElector(ABC):
    """Decides the cluster's leader set. Implementations: Bully (default), Raft, etc.

    ``leader_set_size`` is a property of the strategy rather than a fixed "1"
    baked into this interface, so a future multi-leader strategy is a drop-in
    replacement without changing callers.
    """

    @property
    @abstractmethod
    def leader_set_size(self) -> int:
        """How many leaders this strategy elects."""

    @abstractmethod
    def current_view(self) -> LeaderView:
        """Returns the most recently decided leader view (does not trigger an election)."""

    @abstractmethod
    def recompute(self, members: List[ClusterMember], now: float) -> LeaderView:
        """Given the current membership snapshot, decides (or re-decides) the leader set.

        Called whenever membership changes or on a timer. Idempotent given the
        same members list and self identity.
        """

    @abstractmethod
    def is_leader(self, peer_id: str) -> bool:
        """Whether the given peer id is currently in the leader set."""
