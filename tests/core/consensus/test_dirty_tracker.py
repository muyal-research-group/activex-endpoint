from axo_endpoint.core.consensus.dirty_tracker import DirtyTracker


def test_should_flush_false_when_nothing_pending():
    tracker = DirtyTracker(max_dirty_count=5)
    assert tracker.should_flush(now=100.0, idle_seconds=2.0) is False


def test_should_flush_true_once_max_dirty_count_reached():
    tracker = DirtyTracker(max_dirty_count=2)
    tracker.mark_function_dirty("f:1", b"a", now=0.0)
    assert tracker.should_flush(now=0.0, idle_seconds=100.0) is False  # only 1 dirty, no idle elapsed
    tracker.mark_function_dirty("f:2", b"b", now=0.0)
    assert tracker.should_flush(now=0.0, idle_seconds=100.0) is True  # 2 dirty == max_dirty_count


def test_should_flush_true_once_idle_seconds_elapsed():
    tracker = DirtyTracker(max_dirty_count=50)
    tracker.mark_function_dirty("f:1", b"a", now=0.0)
    assert tracker.should_flush(now=1.0, idle_seconds=5.0) is False
    assert tracker.should_flush(now=5.0, idle_seconds=5.0) is True


def test_drain_clears_pending_and_returns_accumulated_mutation():
    tracker = DirtyTracker(max_dirty_count=50)
    tracker.mark_function_dirty("f:1", b"a", now=0.0)
    tracker.mark_function_dirty("f:2", b"b", now=1.0)

    mutation = tracker.drain()
    assert mutation.function_changes == {"f:1": b"a", "f:2": b"b"}
    assert tracker.should_flush(now=100.0, idle_seconds=0.0) is False

    empty_mutation = tracker.drain()
    assert empty_mutation.function_changes == {}


def test_should_flush_true_when_only_data_pending_no_functions():
    # Regression guard: a data-only pending set (no function_changes at all)
    # must still be flush-eligible on its own -- this is the DirtyTracker
    # half of the fix for the run_consensus_tick early-return bug, which
    # previously only gated on function_changes.
    tracker = DirtyTracker(max_dirty_count=2)
    tracker.mark_data_dirty("d:1", b"a", now=0.0)
    assert tracker.should_flush(now=0.0, idle_seconds=100.0) is False
    tracker.mark_data_dirty("d:2", b"b", now=0.0)
    assert tracker.should_flush(now=0.0, idle_seconds=100.0) is True


def test_drain_clears_pending_data_and_returns_accumulated_mutation():
    tracker = DirtyTracker(max_dirty_count=50)
    tracker.mark_data_dirty("d:1", b"a", now=0.0)
    tracker.mark_function_dirty("f:1", b"b", now=1.0)

    mutation = tracker.drain()
    assert mutation.data_changes == {"d:1": b"a"}
    assert mutation.function_changes == {"f:1": b"b"}
    assert tracker.should_flush(now=100.0, idle_seconds=0.0) is False

    empty_mutation = tracker.drain()
    assert empty_mutation.data_changes == {}
