from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class DataBucket:
    """Read-model aggregate for one named, quota-enforced bucket -- mirrors
    domain/execution/job.py's Job shape (plain dataclass + to_dict(), no
    domain behavior methods needed here). Backed by the dedicated `buckets`
    Mongo collection via infrastructure/database/mongo/bucket_repository.py's
    MongoBucketRepository, fed by application/projector/bucket_handler.py
    after a DataBucketCreated event lands in Kurrent."""

    name: str
    quota_bytes: int
    # Sourced from the forwarded event's own EventEnvelope.created_at (an
    # ISO datetime string once decoded off Kurrent/JSON), not the epoch
    # float axo_endpoint's own BucketRegistry uses internally -- matches
    # Function.deleted_at's string-typed convention for envelope timestamps.
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "quota_bytes": self.quota_bytes, "created_at": self.created_at}
