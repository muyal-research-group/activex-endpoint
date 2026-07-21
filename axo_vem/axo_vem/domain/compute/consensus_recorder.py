from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class ConsensusRecorder(ABC):
    """Records one endpoint's reported cluster-consensus fact (LeaderElected,
    ConsensusViewChanged, ClusterQuorum*, ClusterDegraded). Not a domain
    aggregate -- consensus has no invariants or lifecycle of its own, it's a
    per-observer report deduplicated at the read-model level (see
    infrastructure/database/mongo/consensus_repository.py). Lives under
    domain/compute since endpoints are the ones reporting these facts."""

    @abstractmethod
    def record(self, endpoint_id: str, data: Dict[str, Any]) -> None: ...
