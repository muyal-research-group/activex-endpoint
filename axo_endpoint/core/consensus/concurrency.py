from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

_VALID_STRATEGIES = ("round_robin", "random", "two_choices")


def pool_metrics_key(function_id: str, version: int) -> str:
    """The gossiped-metrics dict key for one (function_id, version)'s pool
    summary -- shared by ContainerSummoner.pool_summary() (producer) and
    ConcurrencyLedger.ingest_peer_metrics() (consumer) so the format lives
    in exactly one place."""
    return f"{function_id}::{version}"


def parse_pool_metrics_key(key: str) -> Optional[Tuple[str, int]]:
    """Inverse of pool_metrics_key(); returns None for a malformed key
    rather than raising, since this parses data that arrived over gossip."""
    function_id, sep, version_str = key.rpartition("::")
    if not sep:
        return None
    try:
        return function_id, int(version_str)
    except ValueError:
        return None


@dataclass(frozen=True)
class SlotDecision:
    """The leader's answer to a placement request for one job.

    - ``"granted"``: grow a new container here, using ``slot_index``.
    - ``"place"``: forward the job to ``target_endpoint_id``, an existing owner.
    - ``"retry"``: the ledger isn't reconciled yet (mid leader failover) --
      fail fast, no blocking; the caller surfaces a retryable error.
    """

    action: str
    slot_index: Optional[int] = None
    target_endpoint_id: Optional[str] = None

    @staticmethod
    def granted(slot_index: int) -> "SlotDecision":
        return SlotDecision(action="granted", slot_index=slot_index)

    @staticmethod
    def place(target_endpoint_id: str) -> "SlotDecision":
        return SlotDecision(action="place", target_endpoint_id=target_endpoint_id)

    @staticmethod
    def retry() -> "SlotDecision":
        return SlotDecision(action="retry")


@dataclass(frozen=True)
class ContainerCountEntry:
    """One live container an endpoint reports about itself, for
    CONCURRENCY_RECONCILE_PULL / ConcurrencyLedger.reconcile()."""

    function_id: str
    version: int
    slot_index: int


class ConcurrencyLedger:
    """Leader-side, in-memory, sole authority over which endpoint owns which
    pool slot for a (function_id, version) -- this is what makes
    RuntimeSpec.max_concurrency a strict, cluster-wide cap instead of a
    per-endpoint one, and (since slot indices come from here rather than
    each endpoint's own locally-recomputed `len(pool)`) fixes the 409 race
    in ContainerSummoner.summon() as a side effect.

    Starts ready (usable immediately, empty) rather than gated behind a
    first reconciliation -- only an actual leader failover clears
    readiness, via begin_reconciliation()/reconcile(). This keeps a
    single-endpoint deployment (which is always its own leader from the
    moment BullyLeaderElector is constructed) from ever seeing a spurious
    "retry" on the very first job a function ever receives.
    """

    def __init__(self, strategy: str = "round_robin") -> None:
        self._strategy = strategy if strategy in _VALID_STRATEGIES else "round_robin"
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._ready.set()
        # (function_id, version) -> {slot_index: owning_endpoint_id}
        self._grants: Dict[Tuple[str, int], Dict[int, str]] = {}
        # (function_id, version) -> {endpoint_id: (live, idle)}, fed by
        # heartbeat-gossiped container_pools metrics.
        self._pool_metrics: Dict[Tuple[str, int], Dict[str, Tuple[int, int]]] = {}
        # (function_id, version) -> next round_robin position
        self._rr_cursor: Dict[Tuple[str, int], int] = {}

    # ── placement ────────────────────────────────────────────────────────────

    def request_slot(
        self, function_id: str, version: int, max_concurrency: int, requester_id: str,
    ) -> SlotDecision:
        """Decides where a job for (function_id, version) should run, given
        the requesting endpoint has no idle local container of its own."""
        if not self._ready.is_set():
            return SlotDecision.retry()

        with self._lock:
            key = (function_id, version)
            grants = self._grants.setdefault(key, {})
            owners = sorted(set(grants.values()))

            # Exclude the requester itself: it already checked its own live
            # local state (find_idle()) and got nothing, which is exactly
            # why it's asking. Gossiped pool_metrics about the requester's
            # own containers can be up to one heartbeat interval stale, so
            # trusting it here can tell an endpoint "reuse yourself, you're
            # idle" right after it just proved to itself it isn't --
            # starving growth forever under a rapid burst of jobs. Gossip
            # about *other* endpoints is still used as-is; that staleness
            # risk is smaller (an occasional avoidable queue, not a
            # permanent one) and unavoidable without a live query to a peer.
            idle_owners = [
                eid for eid in owners if eid != requester_id and self._idle_count(key, eid) > 0
            ]
            if idle_owners:
                # Reuse always wins over growth -- never cold-start a new
                # container while one already sits idle elsewhere.
                return SlotDecision.place(self._choose(key, idle_owners))

            if len(grants) < max(1, max_concurrency):
                slot_index = self._smallest_unused_index(grants)
                grants[slot_index] = requester_id
                return SlotDecision.granted(slot_index)

            if not owners:
                # max_concurrency <= 0 shouldn't happen (callers clamp to
                # >= 1), but fail safe rather than crash on an empty pool.
                return SlotDecision.retry()
            return SlotDecision.place(self._choose(key, owners))

    def release_slot(self, function_id: str, version: int, slot_index: int, endpoint_id: str) -> None:
        """Frees a slot, but only if it still maps to the releasing
        endpoint -- defensive against a stale or duplicate release."""
        with self._lock:
            key = (function_id, version)
            grants = self._grants.get(key)
            if grants and grants.get(slot_index) == endpoint_id:
                del grants[slot_index]
                if not grants:
                    del self._grants[key]

    def reap_unknown_owners(self, known_endpoint_ids: Set[str]) -> None:
        """Drops any grant whose owner isn't a currently-known cluster
        member -- self-heals capacity leaked by a hard-crashed follower.
        Only ever frees capacity, never threatens the cap."""
        with self._lock:
            for key in list(self._grants.keys()):
                grants = self._grants[key]
                for idx in [i for i, eid in grants.items() if eid not in known_endpoint_ids]:
                    del grants[idx]
                if not grants:
                    del self._grants[key]

    # ── reconciliation (leader failover) ────────────────────────────────────

    def begin_reconciliation(self) -> None:
        """Clears readiness -- new placement requests get 'retry' until
        reconcile() rebuilds the ledger from ground truth."""
        self._ready.clear()

    def reconcile(self, reports: Dict[str, List[ContainerCountEntry]]) -> None:
        """Rebuilds every grant from scratch, from every endpoint's actual
        reported live containers -- the new leader's only source of truth,
        since it inherits no in-memory state from whoever led before it."""
        new_grants: Dict[Tuple[str, int], Dict[int, str]] = {}
        for endpoint_id, entries in reports.items():
            for entry in entries:
                key = (entry.function_id, entry.version)
                new_grants.setdefault(key, {})[entry.slot_index] = endpoint_id
        with self._lock:
            self._grants = new_grants
            self._rr_cursor.clear()
        self._ready.set()

    # ── gossip ingestion ─────────────────────────────────────────────────────

    def ingest_peer_metrics(self, endpoint_id: str, container_pools: Dict[str, Dict[str, int]]) -> None:
        """Records one endpoint's self-reported live/idle container counts
        per function, from its heartbeat-gossiped container_pools metric."""
        with self._lock:
            for raw_key, counts in container_pools.items():
                parsed = parse_pool_metrics_key(raw_key)
                if parsed is None:
                    continue
                self._pool_metrics.setdefault(parsed, {})[endpoint_id] = (
                    int(counts.get("live", 0)), int(counts.get("idle", 0)),
                )

    # ── internals ────────────────────────────────────────────────────────────

    def _idle_count(self, key: Tuple[str, int], endpoint_id: str) -> int:
        _live, idle = self._pool_metrics.get(key, {}).get(endpoint_id, (0, 0))
        return idle

    def _busy_count(self, key: Tuple[str, int], endpoint_id: str) -> int:
        live, idle = self._pool_metrics.get(key, {}).get(endpoint_id, (0, 0))
        return max(0, live - idle)

    def _choose(self, key: Tuple[str, int], candidates: List[str]) -> str:
        """Applies the configured load-balancing strategy over a fixed
        candidate list -- never affects whether growth vs. reuse happens,
        only which existing owner gets picked."""
        if len(candidates) == 1:
            return candidates[0]
        if self._strategy == "round_robin":
            cursor = self._rr_cursor.get(key, 0)
            target = candidates[cursor % len(candidates)]
            self._rr_cursor[key] = cursor + 1
            return target
        if self._strategy == "two_choices":
            sample = random.sample(candidates, 2)
            return min(sample, key=lambda eid: self._busy_count(key, eid))
        return random.choice(candidates)

    @staticmethod
    def _smallest_unused_index(grants: Dict[int, str]) -> int:
        """The smallest non-negative index not already in use -- reused
        after release, so a long-lived cluster's indices don't grow
        unboundedly."""
        i = 0
        while i in grants:
            i += 1
        return i
