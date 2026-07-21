from __future__ import annotations

from abc import ABC, abstractmethod


class StreamAdmin(ABC):
    """Administrative stream operations -- distinct from EventPublisher's
    everyday append-only role. Used by hard-purge (deleting a function
    version's isolated Kurrent stream), not the normal event-forwarding
    path."""

    @abstractmethod
    def delete_stream(self, stream_name: str) -> None:
        """Permanently deletes a stream. Must not be reversible -- the
        stream name must never be written to again (see kurrentdbclient's
        distinction between a soft delete_stream, which allows the name to
        be reappended later, and tombstone_stream, which forbids it
        forever)."""
