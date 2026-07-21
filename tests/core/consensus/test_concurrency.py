from axo_endpoint.core.consensus.concurrency import (
    ConcurrencyLedger,
    ContainerCountEntry,
    SlotDecision,
    parse_pool_metrics_key,
    pool_metrics_key,
)


def test_request_slot_grants_incrementing_indices_up_to_cap():
    ledger = ConcurrencyLedger()

    first = ledger.request_slot("fn1", 1, max_concurrency=2, requester_id="A")
    second = ledger.request_slot("fn1", 1, max_concurrency=2, requester_id="A")

    assert first == SlotDecision.granted(0)
    assert second == SlotDecision.granted(1)


def test_request_slot_places_at_capacity_on_the_current_owner():
    ledger = ConcurrencyLedger()
    ledger.request_slot("fn1", 1, max_concurrency=1, requester_id="A")

    decision = ledger.request_slot("fn1", 1, max_concurrency=1, requester_id="B")

    assert decision == SlotDecision.place("A")


def test_release_frees_index_for_reuse_rather_than_growing_further():
    ledger = ConcurrencyLedger()
    ledger.request_slot("fn1", 1, 2, "A")  # slot 0
    ledger.request_slot("fn1", 1, 2, "A")  # slot 1

    ledger.release_slot("fn1", 1, 0, "A")
    decision = ledger.request_slot("fn1", 1, 2, "B")

    assert decision == SlotDecision.granted(0)


def test_release_is_a_noop_if_the_slot_belongs_to_someone_else():
    ledger = ConcurrencyLedger()
    ledger.request_slot("fn1", 1, 1, "A")

    ledger.release_slot("fn1", 1, 0, "B")  # stale/duplicate release, wrong owner
    decision = ledger.request_slot("fn1", 1, 1, "B")

    assert decision == SlotDecision.place("A")


def test_reuse_wins_over_growth_when_an_owner_reports_idle():
    ledger = ConcurrencyLedger()
    ledger.request_slot("fn1", 1, 5, "A")  # plenty of room to grow
    ledger.ingest_peer_metrics("A", {"fn1::1": {"live": 1, "idle": 1}})

    decision = ledger.request_slot("fn1", 1, 5, "B")

    assert decision == SlotDecision.place("A")


def test_requester_own_stale_idle_gossip_does_not_block_its_own_growth():
    """Regression test: an endpoint that just proved to itself (via
    find_idle()) that it has nothing free must never be told by the leader
    to 'reuse yourself' based on a stale heartbeat snapshot that hasn't
    caught up yet -- that starves growth forever under a burst of jobs sent
    faster than the heartbeat interval, even with room under the cap."""
    ledger = ConcurrencyLedger()
    ledger.request_slot("fn1", 1, 2, "A")  # slot 0, granted to A
    # Stale gossip: still reports A's one container as idle, even though by
    # the time A asks again it's actually busy again (this is the lag that
    # caused the bug).
    ledger.ingest_peer_metrics("A", {"fn1::1": {"live": 1, "idle": 1}})

    decision = ledger.request_slot("fn1", 1, 2, "A")

    assert decision == SlotDecision.granted(1)  # grows, doesn't loop back to A


def test_round_robin_cycles_through_current_owners():
    ledger = ConcurrencyLedger(strategy="round_robin")
    ledger.request_slot("fn1", 1, 2, "A")
    ledger.request_slot("fn1", 1, 2, "B")

    first = ledger.request_slot("fn1", 1, 2, "C")
    second = ledger.request_slot("fn1", 1, 2, "C")

    assert {first.target_endpoint_id, second.target_endpoint_id} == {"A", "B"}
    assert first.target_endpoint_id != second.target_endpoint_id


def test_two_choices_prefers_the_less_busy_owner():
    ledger = ConcurrencyLedger(strategy="two_choices")
    ledger.request_slot("fn1", 1, 2, "A")
    ledger.request_slot("fn1", 1, 2, "B")
    ledger.ingest_peer_metrics("A", {"fn1::1": {"live": 1, "idle": 0}})
    ledger.ingest_peer_metrics("B", {"fn1::1": {"live": 5, "idle": 0}})

    decision = ledger.request_slot("fn1", 1, 2, "C")

    assert decision.target_endpoint_id == "A"


def test_unknown_strategy_falls_back_to_round_robin():
    ledger = ConcurrencyLedger(strategy="not-a-real-strategy")
    ledger.request_slot("fn1", 1, 1, "A")

    decision = ledger.request_slot("fn1", 1, 1, "B")

    assert decision == SlotDecision.place("A")


def test_retry_before_reconciliation_then_recovers_after_reconcile():
    ledger = ConcurrencyLedger()
    ledger.begin_reconciliation()

    assert ledger.request_slot("fn1", 1, 1, "A") == SlotDecision.retry()

    ledger.reconcile({"A": [ContainerCountEntry(function_id="fn1", version=1, slot_index=0)]})
    decision = ledger.request_slot("fn1", 1, 1, "B")

    assert decision == SlotDecision.place("A")


def test_reconcile_fully_replaces_prior_state():
    ledger = ConcurrencyLedger()
    ledger.request_slot("fn1", 1, 1, "A")

    ledger.reconcile({"B": [ContainerCountEntry(function_id="fn1", version=1, slot_index=0)]})
    decision = ledger.request_slot("fn1", 1, 1, "C")

    assert decision == SlotDecision.place("B")  # A's old grant is gone, B's ground truth wins


def test_reap_unknown_owners_frees_a_hard_crashed_followers_grant():
    ledger = ConcurrencyLedger()
    ledger.request_slot("fn1", 1, 1, "A")

    ledger.reap_unknown_owners({"B"})  # A is no longer a known cluster member
    decision = ledger.request_slot("fn1", 1, 1, "B")

    assert decision == SlotDecision.granted(0)


def test_pool_metrics_key_round_trips():
    key = pool_metrics_key("my-fn", 3)
    assert parse_pool_metrics_key(key) == ("my-fn", 3)


def test_parse_pool_metrics_key_rejects_malformed_input():
    assert parse_pool_metrics_key("not-a-valid-key") is None
