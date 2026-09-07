from __future__ import annotations

import json
from typing import Any, Dict

from kurrentdbclient import KurrentDBClient, NewEvent, StreamState

from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.domain.events.stream_admin import StreamAdmin


class KurrentDBAppender(EventPublisher, StreamAdmin):
    """Real EventPublisher backed by kurrentdbclient.KurrentDBClient.
    current_version=StreamState.ANY -- concurrent appenders (the leader vs.
    a follower independently reporting the same consensus fact, or a node
    reconnecting) never conflict on an optimistic-concurrency check; every
    stream here is append-only with no caller-enforced ordering constraint.

    Also implements StreamAdmin (delete_stream) since it already wraps the
    same KurrentDBClient -- no separate connection/class needed for the rare
    hard-purge path.
    """

    def __init__(self, client: KurrentDBClient) -> None:
        self._client = client

    def append_to_stream(self, stream_name: str, event_type: str, data: Dict[str, Any]) -> None:
        self._client.append_to_stream(
            stream_name,
            events=NewEvent(type=event_type, data=json.dumps(data).encode("utf-8")),
            current_version=StreamState.ANY,
        )

    def delete_stream(self, stream_name: str) -> None:
        """Uses tombstone_stream (permanent), not the plain delete_stream
        (soft -- allows the name to be reappended later). Safe to use
        StreamState.ANY here: our stream naming (functions-{id}-{version})
        never gets reused, since version only ever increments."""
        self._client.tombstone_stream(stream_name, current_version=StreamState.ANY)
