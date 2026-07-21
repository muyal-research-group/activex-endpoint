from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional


def push_with_retry(
    attempt_fn: Callable[[], bool],
    max_retries: int,
    backoff_base_seconds: float,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Calls attempt_fn() up to max_retries times, waiting an exponentially
    growing gap between attempts (backoff_base_seconds, *2, *4, ...). Returns
    True on the first success, False if every attempt failed. Generic over
    what "one attempt" means -- callers wrap a local handler call or a real
    wire forward into a zero-arg bool-returning closure."""
    for attempt in range(max(1, max_retries)):
        if attempt_fn():
            return True
        if attempt < max_retries - 1:
            sleep_fn(backoff_base_seconds * (2 ** attempt))
    return False


class ResultConsistencyStore:
    """Per-job_id consistency bookkeeping for replicated job results:
    whether this endpoint's own copy is known synced (with which hash) or
    inconsistent. Separate from the results StorageBackend itself -- this is
    metadata *about* a copy, not the copy's content."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Dict[str, str] = {}
        self._hash: Dict[str, str] = {}

    def mark_synced(self, job_id: str, result_hash: str) -> None:
        with self._lock:
            self._state[job_id] = "synced"
            self._hash[job_id] = result_hash

    def mark_inconsistent(self, job_id: str) -> None:
        with self._lock:
            self._state[job_id] = "inconsistent"

    def get_state(self, job_id: str) -> Optional[str]:
        with self._lock:
            return self._state.get(job_id)

    def get_hash(self, job_id: str) -> Optional[str]:
        with self._lock:
            return self._hash.get(job_id)

    def all_job_ids(self) -> List[str]:
        with self._lock:
            return list(self._state.keys())


class ResultConsistencySweeper:
    """Leader-owned, paginated background re-verification of every job
    result's consistency across the cluster. Advances a cursor over
    ``consistency_store``'s known job ids by ``chunk_size`` entries each
    periodic tick, wrapping around once it reaches the end. A priority list
    (fed by axo_vem-requested single-job checks) is drained on top of that
    tick's chunk_size budget, not counted against it. Only one sync process
    -- scheduled or manual -- runs at a time (single-flight via ``_syncing``);
    a periodic tick due while a manual sync is running is simply skipped.

    ``reverify_fn`` does the actual work for one job id (fetch the canonical
    result, re-push it to every peer) -- kept as an injected callback so this
    class stays free of any wire/transport dependency; the real
    implementation lives in the service layer (job_result_sync.py)."""

    def __init__(
        self,
        consistency_store: ResultConsistencyStore,
        reverify_fn: Callable[[str], None],
        chunk_size: int,
    ) -> None:
        self._consistency_store = consistency_store
        self._reverify_fn = reverify_fn
        self._chunk_size = max(1, chunk_size)
        self._lock = threading.Lock()
        self._syncing = False
        self._cursor = 0
        self._priority: List[str] = []
        # -inf, not 0.0 -- so the very first maybe_run_periodic() call always
        # runs regardless of what `now` happens to be, rather than requiring
        # a full interval to have elapsed since an arbitrary epoch.
        self._last_run_at = float("-inf")

    def request_priority_check(self, job_id: str) -> None:
        with self._lock:
            if job_id not in self._priority:
                self._priority.append(job_id)

    def maybe_run_periodic(self, now: float, interval_seconds: float) -> bool:
        """Called frequently from App's own loop; only actually advances the
        sweep once interval_seconds has elapsed since the last run, and only
        if nothing else is currently syncing. Returns whether it ran."""
        with self._lock:
            if self._syncing or (now - self._last_run_at) < interval_seconds:
                return False
            self._last_run_at = now
            self._syncing = True
        try:
            self._run_step()
        finally:
            with self._lock:
                self._syncing = False
        return True

    def start_manual_sync(self) -> bool:
        """Kicks off a full pass right now, chunk_size-at-a-time, back to
        back with no waiting between steps. Returns False (does nothing) if
        a sync -- scheduled or manual -- is already in progress."""
        with self._lock:
            if self._syncing:
                return False
            self._syncing = True
        threading.Thread(target=self._run_manual_pass, daemon=True).start()
        return True

    def is_syncing(self) -> bool:
        with self._lock:
            return self._syncing

    def _run_manual_pass(self) -> None:
        try:
            total = len(self._consistency_store.all_job_ids())
            steps = max(1, (total // self._chunk_size) + 1)
            for _ in range(steps):
                self._run_step()
        finally:
            with self._lock:
                self._syncing = False

    def _run_step(self) -> None:
        with self._lock:
            priority_batch, self._priority = self._priority, []
        all_ids = self._consistency_store.all_job_ids()
        batch: List[str] = []
        if all_ids:
            n = len(all_ids)
            start = self._cursor % n
            batch = [all_ids[(start + i) % n] for i in range(min(self._chunk_size, n))]
            self._cursor = (start + len(batch)) % n
        targets = list(dict.fromkeys(priority_batch + batch))
        for job_id in targets:
            self._reverify_fn(job_id)
