from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class DataItem:
    """Read-model aggregate for one registered piece of data (one name+version).
    ``name`` follows the "{bucket}/{key}" convention when registered into a
    bucket, or is a bare name for unbucketed data. Backed by the dedicated
    `bucket_data` Mongo collection via
    infrastructure/database/mongo/bucket_repository.py's MongoDataItemRepository,
    fed by application/projector/bucket_handler.py after a DataRegistered
    (status="pending") or DataUploadCompleted (status="ready") event lands
    in Kurrent.

    ``status`` exists so the UI can render an in-progress upload immediately
    (as soon as metadata registers) instead of it being silently absent
    until every chunk has also landed -- see the plan this was built from.
    """

    name: str
    version: int
    format: str
    kind: str
    total_size: int
    total_chunks: int
    status: str  # "pending" | "ready"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "version": self.version, "format": self.format,
            "kind": self.kind, "total_size": self.total_size, "total_chunks": self.total_chunks,
            "status": self.status,
        }
