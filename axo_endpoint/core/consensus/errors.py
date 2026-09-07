from __future__ import annotations

from axo_endpoint.core.errors import AxoError

# ── 6xxx: consensus / replication ─────────────────────────────────────────────


class LeaderUnreachableError(AxoError):
    """A follower's attempt to forward a command to the current leader failed
    (leader unknown, unresolvable, or unreachable within the forward timeout).

    Only surfaced to a client when forwarding itself fails — not a routine
    "go ask someone else" signal (see LeaderProxyHandler, which forwards
    transparently in the normal case).
    """

    code = 6001
    name = "LEADER_UNREACHABLE"


class StaleTermError(AxoError):
    """A STATE_SYNC_PUSH arrived with a term older than what we already have."""

    code = 6002
    name = "STALE_TERM"


class ElectionInProgressError(AxoError):
    """Reserved for a future message-passing election strategy; unused by BullyLeaderElector."""

    code = 6003
    name = "ELECTION_IN_PROGRESS"


class ReplicationRejectedError(AxoError):
    """Reserved for future STATE_SYNC_PUSH validation failures beyond stale term."""

    code = 6004
    name = "REPLICATION_REJECTED"


class ConcurrencyLedgerNotReadyError(AxoError):
    """A CONCURRENCY_SLOT_REQUEST arrived while the leader's ConcurrencyLedger
    is mid-reconciliation (just after a failover) -- retryable, not fatal."""

    code = 6005
    name = "CONCURRENCY_LEDGER_NOT_READY"
