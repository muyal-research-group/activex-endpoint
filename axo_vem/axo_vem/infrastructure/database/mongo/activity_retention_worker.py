from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Union

from axo_shared.events import models

from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository
from axo_vem.log import DumbLogger, Log
from axo_vem.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]

# Event types where a later row fully supersedes an earlier one's meaning
# for the same group -- the single overall newest row per group is kept
# forever, older ones are purged once they age past the retention ceiling
# (see MongoActivityRepository.purge_superseded). Extending this to
# FunctionActivated/FunctionDeactivated/FunctionStopped later is a cheap,
# natural extension of the same mechanism -- not done yet, out of scope for
# now.
SUPERSEDABLE_GROUPS: List[Tuple[str, List[str]]] = [
    # FunctionUpdated's own field is "version" (matching FunctionRegistered/
    # FunctionDeployed's convention), not "function_version" (a Job*-event
    # convention) -- meta.version is the correct grouping key here.
    (models.FUNCTION_UPDATED, ["function_id", "version"]),
]


class ActivityRetentionWorker:
    """Background daemon thread (same sleep-loop pattern as
    KurrentSubscriber and EndpointStatsPoller) that hard-deletes
    unified_activity rows older than a fixed system-wide ceiling
    (AXO_VEM_ACTIVITY_RETENTION_HOURS), on its own,
    independent tick cadence (AXO_VEM_ACTIVITY_RETENTION_TICK_SECONDS)
    -- deliberately not the same cadence as anything user-facing, since this
    is pure cleanup, not something anyone is waiting on.

    This ceiling is entirely independent of any individual user's
    activity_window_minutes display preference (see
    infrastructure/transport/api/controllers/history.py's _since_for) --
    that's just a default for how far back a caller's own view starts;
    this is the actual point past which the data stops existing at all.
    """

    def __init__(
        self,
        activity_repository: MongoActivityRepository,
        retention_hours: float,
        tick_seconds: float = 300.0,
        logger: _Logger = None,
    ) -> None:
        self._activity_repository = activity_repository
        self._retention_hours = retention_hours
        self._tick_seconds = tick_seconds
        self._logger: _Logger = logger or DumbLogger()
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def run_forever(self) -> None:
        while not self._stopped:
            self.tick()
            time.sleep(self._tick_seconds)

    def tick(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._retention_hours)
        try:
            # Supersedable event types are entirely excluded from the blanket
            # age purge -- their retention is handled exclusively by
            # purge_superseded below, which alone knows to keep each group's
            # single newest row forever regardless of age.
            superseded_event_types = [event_type for event_type, _ in SUPERSEDABLE_GROUPS]
            deleted_count = self._activity_repository.purge_older_than(
                cutoff, exclude_event_types=superseded_event_types,
            )
            for event_type, group_by_fields in SUPERSEDABLE_GROUPS:
                deleted_count += self._activity_repository.purge_superseded(event_type, group_by_fields, cutoff)
        except Exception as exc:
            self._logger.error_event(
                Event.ActivityRetention.TICK_FAILED,
                component=Component.ACTIVITY_RETENTION,
                error=str(exc),
            )
            return
        if deleted_count:
            self._logger.info_event(
                Event.ActivityRetention.PURGED,
                component=Component.ACTIVITY_RETENTION,
                deleted_count=deleted_count,
                cutoff=cutoff.isoformat(),
            )
