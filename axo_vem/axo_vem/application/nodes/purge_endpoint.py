from __future__ import annotations

from typing import Any, Dict

from pymongo.collection import Collection

from axo_vem.domain.compute.repository import FunctionRepository
from axo_vem.domain.errors import ConflictError, NotFoundError
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.domain.events.stream_naming import stream_name_for
from axo_vem.domain.execution.job import JobStatus
from axo_vem.domain.execution.repository import JobRepository
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository


class PurgeEndpointUseCase:
    """Hard-deletes this endpoint's read-model doc and its unified_activity
    history -- same as the former inline route body -- but first cascades
    to every function this endpoint was a holder of: the endpoint is
    confirmed gone (same stopped/unreachable precondition as before), so any
    of its own jobs still reading QUEUED/STARTED were never going to finish
    and get force-failed here (a real JobFailed event, not a blocking
    check) -- scoped to jobs whose own endpoint_id is this one, since a
    function held by multiple endpoints can have live jobs running
    elsewhere that this purge has no bearing on.

    A function then gets one of two outcomes, depending on whether this was
    its last recorded holder: if other endpoints still hold it, a
    FunctionEndpointDetached event just removes this one entry from its
    endpoint_id list (compute_handler.apply()'s FUNCTION_ENDPOINT_DETACHED
    branch -> FunctionRepository.detach_endpoint_from_event); only when this
    was the last holder does it get a real FunctionDeleted event, the same
    soft-delete an organic FUNCTION_DELETE command produces
    (compute_handler.apply()'s FUNCTION_DELETED branch).

    Never touches the underlying Kurrent event log for the endpoint itself
    (same as before) -- only the cascaded Job*/Function* events are real
    domain events; endpoint purge stays a pure physical-cleanup operation.
    """

    def __init__(
        self,
        endpoints: Collection,
        activity_repository: MongoActivityRepository,
        function_repository: FunctionRepository,
        job_repository: JobRepository,
        event_publisher: EventPublisher,
    ) -> None:
        self._endpoints = endpoints
        self._activity_repository = activity_repository
        self._function_repository = function_repository
        self._job_repository = job_repository
        self._event_publisher = event_publisher

    def execute(self, *, endpoint_id: str) -> Dict[str, Any]:
        doc = self._endpoints.find_one({"_id": endpoint_id})
        if doc is None:
            raise NotFoundError("endpoint not found")
        if doc.get("status") not in ("stopped", "unreachable"):
            raise ConflictError("endpoint must be stopped or unreachable before it can be purged")

        functions_marked_deleted = 0
        functions_detached = 0
        jobs_force_failed = 0
        for function in self._function_repository.list_by_endpoint_id(endpoint_id):
            for job in self._job_repository.list_by_function(function.function_id, function.version):
                if job.status not in (JobStatus.QUEUED, JobStatus.STARTED) or job.endpoint_id != endpoint_id:
                    continue
                self._append(
                    endpoint_id, models.JOB_FAILED,
                    models.JobFailed(
                        job_id=job.job_id,
                        function_id=function.function_id,
                        failure=models.FailureDetail(
                            error_class="EndpointPurged",
                            error_code=0,
                            component="axo_vem.purge_endpoint",
                            message=(
                                f"endpoint {endpoint_id} was purged while this job was still "
                                f"{job.status.value.lower()}"
                            ),
                        ),
                        duration_ms=job.duration_ms,
                        endpoint_id=endpoint_id,
                    ),
                )
                jobs_force_failed += 1

            remaining_holders = [e for e in function.endpoint_id if e != endpoint_id]
            if remaining_holders:
                self._append(
                    endpoint_id, models.FUNCTION_ENDPOINT_DETACHED,
                    models.FunctionEndpointDetached(
                        function_id=function.function_id, version=function.version, endpoint_id=endpoint_id,
                    ),
                )
                functions_detached += 1
            else:
                self._append(
                    endpoint_id, models.FUNCTION_DELETED,
                    models.FunctionDeleted(
                        function_id=function.function_id, version=function.version, endpoint_id=endpoint_id,
                    ),
                )
                functions_marked_deleted += 1

        self._endpoints.delete_one({"_id": endpoint_id})
        purged_activity_count = self._activity_repository.purge(endpoint_id=endpoint_id)
        return {
            "endpoint_id": endpoint_id,
            "purged_activity_count": purged_activity_count,
            "functions_marked_deleted": functions_marked_deleted,
            "functions_detached": functions_detached,
            "jobs_force_failed": jobs_force_failed,
        }

    def _append(self, endpoint_id: str, event_type: str, event: Any) -> None:
        data = event.model_dump(mode="json")
        stream = stream_name_for(event_type, endpoint_id, data)
        self._event_publisher.append_to_stream(stream, event_type, data)
