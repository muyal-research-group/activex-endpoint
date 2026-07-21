from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClusterMember:
    """One node's identity as known to consensus.

    Deliberately thinner than ``PeerInfo`` (no metrics/latency/last_seen) so
    ``core.consensus`` stays decoupled from the heartbeat wire format — callers
    project ``PeerInfo`` down to this before calling ``LeaderElector.recompute``.
    """

    peer_id: str
    rpc_uri: str
