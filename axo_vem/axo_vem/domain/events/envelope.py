from __future__ import annotations

"""Re-exports axo_shared.events.envelope -- see domain/events/models.py for
why the taxonomy itself stays defined in the shared sibling package."""

from axo_shared.events.envelope import (
    SCHEMA_VERSION,
    EVENT_TYPES,
    encode_event,
    decode_event,
    rehydrate,
)

__all__ = [
    "SCHEMA_VERSION",
    "EVENT_TYPES",
    "encode_event",
    "decode_event",
    "rehydrate",
]
