from __future__ import annotations

from typing import Protocol, Sequence

from axo_vem.infrastructure.database.kurrent.types import RecordedEventLike


class KurrentReader(Protocol):
    """Narrow read interface the raw-events route needs -- separate from
    EventPublisher (ingestion/route writes) and the subscriber's
    subscribe_to_all, so that route is independently fakeable in tests.
    Moved from api/routes/events.py."""

    def get_stream(self, stream_name: str) -> Sequence[RecordedEventLike]: ...
