from __future__ import annotations

import time
from typing import Callable, Union

from axo_shared.activity.models import ActivityRecord
from axo_shared.activity.repository import Repository
from axo_endpoint.core.events.bus import Event
from axo_endpoint.core.storage.backend import StorageBackend, StorageKey


class ActivityTrackingBridge:
    """Bridges core.activity <-> the rest of the system without either
    depending on the other, mirroring RegistrySyncBridge/DataRegistrySyncBridge.
    Subscribes to the existing job-lifecycle events and the new
    container-lifecycle events, recording one ActivityRecord per raw event --
    no handler anywhere else needs to change.
    """

    def __init__(
        self,
        repository: Repository[ActivityRecord],
        results: StorageBackend,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._repository = repository
        self._results = results
        self._now_fn = now_fn

    def on_job_submitted(self, event: Event) -> None:
        """Subscribed to JOB_SUBMITTED."""
        job_id = event.payload["job_id"]
        function_id = event.payload["function_id"]
        self._repository.save(ActivityRecord(
            id=f"{job_id}:{event.event_type}",
            activity_type=event.event_type,
            function_id=function_id,
            function_version=None,
            job_id=job_id,
            timestamp=event.timestamp,
        ))

    def on_job_finished(self, event: Event) -> None:
        """Subscribed to JOB_COMPLETED/JOB_FAILED. The bus payload is
        intentionally thin (job_id, function_id only) -- the full
        FunctionResult (ok, values, error) lives in the results
        StorageBackend, fetched here the same way RouterServer._on_job_event
        already does it."""
        job_id = event.payload["job_id"]
        function_id = event.payload["function_id"]
        get_result = self._results.get(StorageKey(id=job_id))
        result = get_result.unwrap() if get_result.is_ok else None
        failure = None
        if result is not None and not result.ok:
            failure = {
                "error_class": "FUNCTION_RUNTIME_ERROR",
                "error_code": 0,
                "component": "runtime",
                "message": result.error,
                "traceback": None,
                "is_transient": False,
            }
        self._repository.save(ActivityRecord(
            id=f"{job_id}:{event.event_type}",
            activity_type=event.event_type,
            function_id=function_id,
            function_version=None,
            job_id=job_id,
            timestamp=event.timestamp,
            failure=failure,
        ))

    def on_container_event(self, event: Event) -> None:
        """Subscribed to CONTAINER_SPAWNED/READY/CRASHED/DISMISSED."""
        function_id = event.payload.get("function_id", "")
        self._repository.save(ActivityRecord(
            id=f"{function_id}:{event.event_type}:{event.timestamp}",
            activity_type=event.event_type,
            function_id=function_id,
            function_version=event.payload.get("version"),
            job_id=None,
            timestamp=event.timestamp,
            service_name=event.payload.get("service_name"),
        ))
