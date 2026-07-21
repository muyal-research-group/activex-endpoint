from __future__ import annotations

import threading
from typing import List

from axo_endpoint.core.consensus.elector import LeaderElector, LeaderView
from axo_endpoint.core.consensus.membership import ClusterMember


class BullyLeaderElector(LeaderElector):
    """Deterministic, message-free Bully variant.

    The leader is always the member with the lexicographically-highest
    peer_id among currently-alive members (self included). There are no
    ELECTION/OK/COORDINATOR RPCs — membership itself (from heartbeat) is the
    only signal, so "re-election" is just recomputing this pure function
    again. Every node sees the same membership and self id space, so every
    node converges on the same winner independently, with no coordination.
    """

    def __init__(self, self_id: str) -> None:
        self._self_id = self_id
        self._view = LeaderView(leader_ids=frozenset({self_id}), term=0, decided_at=0.0)
        self._lock = threading.Lock()

    @property
    def leader_set_size(self) -> int:
        return 1

    def current_view(self) -> LeaderView:
        with self._lock:
            return self._view

    def recompute(self, members: List[ClusterMember], now: float) -> LeaderView:
        all_ids = {m.peer_id for m in members} | {self._self_id}
        winner = max(all_ids)
        with self._lock:
            if self._view.leader_ids != frozenset({winner}):
                self._view = LeaderView(
                    leader_ids=frozenset({winner}), term=self._view.term + 1, decided_at=now
                )
            return self._view

    def is_leader(self, peer_id: str) -> bool:
        return peer_id in self.current_view().leader_ids
