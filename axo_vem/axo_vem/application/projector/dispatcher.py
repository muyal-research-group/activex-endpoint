from __future__ import annotations

import time
from typing import Any, Dict, Optional, Union

from axo_vem.application.projector import (
    bucket_handler,
    compute_handler,
    identity_handler,
    job_handler,
    workspace_handler,
)
from axo_vem.application.projector.handlers import ProjectorHandlers
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.infrastructure.transport.ws.broadcaster import Broadcaster
from axo_vem.log import DumbLogger, Log
from axo_vem.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]

# Common identifying-field names to surface in the EVENT_APPLIED log,
# checked in order -- every event type carries at most one of these, so this
# is just "pick whichever is present" rather than a per-type mapping.
_ENTITY_ID_FIELDS = (
    "endpoint_id", "function_id", "user_id", "virtual_environment_id",
    "job_id", "bucket", "consumer_group",
)

# Event types with no dedicated aggregate collection of their own -- they
# only ever land in unified_activity (recorded unconditionally below).
# Job* events have their own dedicated jobs collection (job_handler.py) and
# are deliberately NOT in this set.
ACTIVITY_ONLY_EVENT_TYPES = frozenset({
    models.FUNCTION_DELETE_FAILED,
    models.FUNCTION_BUILD_STARTED, models.FUNCTION_BUILD_COMPLETED, models.FUNCTION_BUILD_FAILED,
})

_USER_PROFILE_EVENT_TYPES = identity_handler.UPSERT_EVENT_TYPES | {models.USER_PROFILE_DELETED}
_VIRTUAL_ENV_EVENT_TYPES = frozenset({
    models.VIRTUAL_ENV_CREATED, models.VIRTUAL_ENV_UPDATED, models.VIRTUAL_ENV_DELETED,
    models.VIRTUAL_ENV_LEADER_CHANGED,
})

# Every event type apply_event recognizes -- checked up front so an
# unrecognized event_type still raises ValueError with zero side effects,
# rather than partially recording into unified_activity first.
_ALL_KNOWN_EVENT_TYPES = (
    compute_handler.ENDPOINT_EVENT_TYPES | compute_handler.FUNCTION_EVENT_TYPES
    | {models.FUNCTION_DELETED, models.FUNCTION_ENDPOINT_DETACHED}
    | ACTIVITY_ONLY_EVENT_TYPES | compute_handler.CONSENSUS_EVENT_TYPES
    | _USER_PROFILE_EVENT_TYPES | _VIRTUAL_ENV_EVENT_TYPES | job_handler.JOB_EVENT_TYPES
    | bucket_handler.BUCKET_EVENT_TYPES
)


def apply_event(
    handlers: ProjectorHandlers, event_type: str, data: Dict[str, Any], broadcaster: Optional[Broadcaster] = None,
    logger: _Logger = None, event_publisher: Optional[EventPublisher] = None,
) -> None:
    """Dispatches one decoded (event_type, data) pair to the right
    aggregate handler. endpoint_id is read out of `data` itself rather than
    passed separately -- every typed event carries its own endpoint_id field
    (see axo_shared/events/models.py's EventEnvelope).

    Every recognized event type is unconditionally recorded into
    unified_activity first via activity_recorder.record(), then routed to
    whatever other aggregate handler (if any) it also belongs to -- one call
    site that can't be missed by future edits to the per-type branches
    below. Replaces projector/upserts.py's former apply_event.

    ``broadcaster`` is optional (defaults to None, a no-op) purely so
    existing callers -- server.py always passes a real one, but plenty of
    tests construct ProjectorHandlers without caring about WS delivery --
    don't need to thread one through just to exercise the Mongo write.

    ``logger`` defaults to a no-op DumbLogger for the same reason. On
    success this is the single place that logs EVENT_APPLIED for every
    entity type this projector handles -- one log line here covers
    endpoints/functions/consensus/profiles/virtual-environments/jobs/buckets
    without threading a logger through each of the per-type handler modules
    individually."""
    _logger: _Logger = logger or DumbLogger()

    if event_type not in _ALL_KNOWN_EVENT_TYPES:
        raise ValueError(f"unknown event_type: {event_type!r}")

    t0 = time.monotonic()
    handlers.activity_recorder.record(event_type, data)

    if event_type in compute_handler.ENDPOINT_EVENT_TYPES or event_type in compute_handler.FUNCTION_EVENT_TYPES \
            or event_type in (models.FUNCTION_DELETED, models.FUNCTION_ENDPOINT_DETACHED) \
            or event_type in compute_handler.CONSENSUS_EVENT_TYPES:
        compute_handler.apply(
            handlers.endpoint_repository, handlers.function_repository, handlers.consensus_recorder,
            event_type, data, broadcaster,
            virtual_environment_repository=handlers.virtual_environment_repository,
            event_publisher=event_publisher,
        )
    elif event_type in ACTIVITY_ONLY_EVENT_TYPES:
        pass  # already recorded above; no other aggregate handler to route to
    elif event_type in _USER_PROFILE_EVENT_TYPES:
        identity_handler.apply(handlers.user_profile_repository, event_type, data)
    elif event_type in _VIRTUAL_ENV_EVENT_TYPES:
        workspace_handler.apply(handlers.virtual_environment_repository, event_type, data)
    elif event_type in job_handler.JOB_EVENT_TYPES:
        job_handler.apply(handlers.job_repository, event_type, data)
    elif event_type in bucket_handler.BUCKET_EVENT_TYPES:
        bucket_handler.apply(handlers.bucket_repository, handlers.data_item_repository, event_type, data, broadcaster)

    entity_id = next((data[field] for field in _ENTITY_ID_FIELDS if field in data), None)
    _logger.info_event(
        Event.Projector.EVENT_APPLIED,
        component=Component.PROJECTOR,
        event_type=event_type,
        entity_id=entity_id,
        duration_ms=round((time.monotonic() - t0) * 1000, 2),
    )
