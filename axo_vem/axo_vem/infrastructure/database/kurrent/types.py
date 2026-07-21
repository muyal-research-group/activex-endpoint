from __future__ import annotations

from typing import Protocol


class RecordedEventLike(Protocol):
    """The minimal shape the subscriber/projector needs from a Kurrent
    RecordedEvent -- narrowed so tests can feed in plain fakes without a
    real client. Moved from projector/projector.py."""

    type: str
    data: bytes
    commit_position: int
