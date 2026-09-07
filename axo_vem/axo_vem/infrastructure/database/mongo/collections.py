from __future__ import annotations

from dataclasses import dataclass

from pymongo.collection import Collection


@dataclass(frozen=True)
class ReadCollections:
    """Bundles the raw pymongo Collections that GET controllers for
    Endpoint/Function/consensus read directly (decision 3 in the migration
    plan: these have no well-defined shape to safely reconstruct into
    aggregates for HTTP responses, so they stay dict-based). Purely a
    read-side convenience for infrastructure/transport/api/app.py -- the
    write side uses application/projector/handlers.py's ProjectorHandlers
    instead, which bundles domain-typed repositories rather than raw
    collections. Replaces the read-facing half of projector/upserts.py's
    former ProjectorCollections."""

    endpoints: Collection
    functions: Collection
    consensus: Collection
