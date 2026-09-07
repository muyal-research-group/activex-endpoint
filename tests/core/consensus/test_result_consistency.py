import threading
import time

from axo_endpoint.core.consensus.result_consistency import (
    ResultConsistencySweeper,
    ResultConsistencyStore,
    push_with_retry,
)


def test_push_with_retry_succeeds_on_first_attempt():
    calls = []

    def attempt() -> bool:
        calls.append(1)
        return True

    assert push_with_retry(attempt, max_retries=3, backoff_base_seconds=0.01, sleep_fn=lambda s: None) is True
    assert len(calls) == 1


def test_push_with_retry_retries_with_exponential_backoff_then_succeeds():
    calls = []
    slept = []

    def attempt() -> bool:
        calls.append(1)
        return len(calls) >= 3

    ok = push_with_retry(attempt, max_retries=5, backoff_base_seconds=1.0, sleep_fn=slept.append)

    assert ok is True
    assert len(calls) == 3
    assert slept == [1.0, 2.0]  # doubling, one sleep between each failed attempt


def test_push_with_retry_exhausts_all_attempts_and_fails():
    calls = []

    def attempt() -> bool:
        calls.append(1)
        return False

    ok = push_with_retry(attempt, max_retries=3, backoff_base_seconds=0.01, sleep_fn=lambda s: None)

    assert ok is False
    assert len(calls) == 3


def test_consistency_store_tracks_synced_and_inconsistent_state():
    store = ResultConsistencyStore()

    store.mark_synced("job1", "hash1")
    assert store.get_state("job1") == "synced"
    assert store.get_hash("job1") == "hash1"

    store.mark_inconsistent("job1")
    assert store.get_state("job1") == "inconsistent"


def test_consistency_store_unknown_job_id_returns_none():
    store = ResultConsistencyStore()
    assert store.get_state("missing") is None
    assert store.get_hash("missing") is None


def test_sweeper_advances_cursor_by_chunk_size_and_wraps_around():
    store = ResultConsistencyStore()
    for i in range(5):
        store.mark_synced(f"job{i}", "h")
    seen = []
    sweeper = ResultConsistencySweeper(store, reverify_fn=seen.append, chunk_size=2)

    sweeper.maybe_run_periodic(now=0.0, interval_seconds=10.0)
    assert len(seen) == 2  # job0, job1
    sweeper.maybe_run_periodic(now=10.0, interval_seconds=10.0)
    assert len(seen) == 4  # job2, job3
    sweeper.maybe_run_periodic(now=20.0, interval_seconds=10.0)
    # Cursor wraps mid-chunk rather than stopping short at the list boundary
    # -- job4 (the last new one) plus job0 (revisited, cursor wrapped).
    assert seen[4:] == ["job4", "job0"]
    sweeper.maybe_run_periodic(now=30.0, interval_seconds=10.0)
    assert seen[6:] == ["job1", "job2"]  # continues advancing, never stalls


def test_sweeper_skips_tick_before_interval_has_elapsed():
    store = ResultConsistencyStore()
    store.mark_synced("job1", "h")
    seen = []
    sweeper = ResultConsistencySweeper(store, reverify_fn=seen.append, chunk_size=10)

    ran_first = sweeper.maybe_run_periodic(now=0.0, interval_seconds=100.0)
    ran_second = sweeper.maybe_run_periodic(now=1.0, interval_seconds=100.0)

    assert ran_first is True
    assert ran_second is False
    assert len(seen) == 1


def test_priority_check_is_added_on_top_of_the_chunk_budget():
    store = ResultConsistencyStore()
    for i in range(3):
        store.mark_synced(f"job{i}", "h")
    seen = []
    sweeper = ResultConsistencySweeper(store, reverify_fn=seen.append, chunk_size=3)

    sweeper.request_priority_check("priority-job")
    sweeper.maybe_run_periodic(now=0.0, interval_seconds=10.0)

    assert "priority-job" in seen
    assert len(seen) == 4  # 3 from the normal chunk + 1 priority, not instead of it


def test_manual_sync_runs_a_full_pass_over_every_known_job():
    store = ResultConsistencyStore()
    for i in range(5):
        store.mark_synced(f"job{i}", "h")
    seen = []
    sweeper = ResultConsistencySweeper(store, reverify_fn=seen.append, chunk_size=2)

    started = sweeper.start_manual_sync()
    assert started is True

    for _ in range(100):
        if not sweeper.is_syncing():
            break
        time.sleep(0.02)

    assert set(seen) == {f"job{i}" for i in range(5)}


def test_manual_sync_is_refused_while_one_is_already_in_progress():
    store = ResultConsistencyStore()
    store.mark_synced("job1", "h")
    release = threading.Event()

    def blocking_reverify(job_id: str) -> None:
        release.wait(timeout=2)

    sweeper = ResultConsistencySweeper(store, reverify_fn=blocking_reverify, chunk_size=1)
    assert sweeper.start_manual_sync() is True
    time.sleep(0.05)  # let the background thread actually enter _syncing

    assert sweeper.start_manual_sync() is False  # single-flight guard

    release.set()


def test_periodic_tick_is_skipped_while_a_manual_sync_is_in_progress():
    store = ResultConsistencyStore()
    store.mark_synced("job1", "h")
    release = threading.Event()

    def blocking_reverify(job_id: str) -> None:
        release.wait(timeout=2)

    sweeper = ResultConsistencySweeper(store, reverify_fn=blocking_reverify, chunk_size=1)
    sweeper.start_manual_sync()
    time.sleep(0.05)

    ran = sweeper.maybe_run_periodic(now=0.0, interval_seconds=0.0)

    assert ran is False
    release.set()
