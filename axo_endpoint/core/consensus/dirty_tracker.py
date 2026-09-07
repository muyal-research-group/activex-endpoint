from __future__ import annotations

import threading
from typing import Dict, Optional

from axo_endpoint.core.consensus.elector import LeaderView
from axo_endpoint.core.consensus.state_machine import StateMutation


class DirtyTracker:
    """Accumulates StateMutations between flushes and decides when a flush is due.

    Replication doesn't happen on every write — it flushes when either
    ``max_dirty_count`` entries have piled up, or ``idle_seconds`` have
    elapsed since the last change, whichever fires first.

    One instance tracks all three replicated domains (functions, data, and
    buckets) rather than one tracker per domain -- extending its
    pending-count/flush/drain logic to include a new domain is what makes a
    that-domain-only pending set flush-eligible on its own (see
    ``pending_count``/``should_flush``).
    """

    def __init__(self, max_dirty_count: int) -> None:
        self._pending_functions: Dict[str, bytes] = {}
        self._pending_data: Dict[str, bytes] = {}
        self._pending_buckets: Dict[str, bytes] = {}
        self._pending_leader_view: Optional[LeaderView] = None
        self._last_change_at: float = 0.0
        self._max_dirty_count = max_dirty_count
        self._lock = threading.Lock()

    def mark_function_dirty(self, key: str, serialized: bytes, now: float) -> None:
        """Records that a function's serialized record changed."""
        with self._lock:
            self._pending_functions[key] = serialized
            self._last_change_at = now

    def mark_data_dirty(self, key: str, serialized: bytes, now: float) -> None:
        """Records that a data record's serialized metadata changed."""
        with self._lock:
            self._pending_data[key] = serialized
            self._last_change_at = now

    def mark_bucket_dirty(self, key: str, serialized: bytes, now: float) -> None:
        """Records that a bucket's serialized metadata changed."""
        with self._lock:
            self._pending_buckets[key] = serialized
            self._last_change_at = now

    def mark_leader_view_dirty(self, view: LeaderView, now: float) -> None:
        """Records that the leader view changed."""
        with self._lock:
            self._pending_leader_view = view
            self._last_change_at = now

    def pending_count(self) -> int:
        """Non-mutating peek at how many entries are waiting on the next flush."""
        with self._lock:
            return (
                len(self._pending_functions)
                + len(self._pending_data)
                + len(self._pending_buckets)
                + (1 if self._pending_leader_view is not None else 0)
            )

    def should_flush(self, now: float, idle_seconds: float) -> bool:
        """True iff there's anything pending AND (dirty_count >= max_dirty_count
        OR now - last_change_at >= idle_seconds)."""
        with self._lock:
            pending_count = (
                len(self._pending_functions)
                + len(self._pending_data)
                + len(self._pending_buckets)
                + (1 if self._pending_leader_view is not None else 0)
            )
            if pending_count == 0:
                return False
            if pending_count >= self._max_dirty_count:
                return True
            return (now - self._last_change_at) >= idle_seconds

    def drain(self) -> StateMutation:
        """Returns everything accumulated since the last drain, and clears the dirty set."""
        with self._lock:
            mutation = StateMutation(
                function_changes=dict(self._pending_functions),
                data_changes=dict(self._pending_data),
                bucket_changes=dict(self._pending_buckets),
                leader_view=self._pending_leader_view,
            )
            self._pending_functions = {}
            self._pending_data = {}
            self._pending_buckets = {}
            self._pending_leader_view = None
            return mutation
