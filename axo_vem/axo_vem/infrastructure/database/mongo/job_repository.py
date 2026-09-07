from __future__ import annotations

from typing import List, Optional

from pymongo.collection import Collection

from axo_vem.domain.execution.job import Job, JobStatus
from axo_vem.domain.execution.repository import JobRepository


class MongoJobRepository(JobRepository):
    """Read/write access to the jobs collection, keyed by job_id -- mirrors
    the shape of MongoVirtualEnvironmentRepository. Written by
    application/projector/job_handler.py, read directly via
    GET /jobs/{job_id} and GET /functions/{function_id}/jobs
    (infrastructure/transport/api/controllers/jobs.py)."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def get(self, job_id: str) -> Optional[Job]:
        doc = self._collection.find_one({"_id": job_id})
        if doc is None:
            return None
        return self._doc_to_job(doc)

    def list_by_function(self, function_id: str, function_version: Optional[int] = None) -> List[Job]:
        query = {"function_id": function_id}
        if function_version is not None:
            query["function_version"] = function_version
        docs = self._collection.find(query).sort("created_at", -1)
        return [self._doc_to_job(doc) for doc in docs]

    def save(self, job: Job) -> None:
        data = {
            "job_id": job.job_id,
            "function_id": job.function_id,
            "status": job.status.value,
            "function_version": job.function_version,
            "duration_ms": job.duration_ms,
            "params": job.params,
            "endpoint_id": job.endpoint_id,
            "created_at": job.created_at,
        }
        self._collection.update_one({"_id": job.job_id}, {"$set": data}, upsert=True)

    @staticmethod
    def _doc_to_job(doc: dict) -> Job:
        return Job(
            job_id=doc["job_id"],
            function_id=doc["function_id"],
            status=JobStatus(doc["status"]),
            function_version=doc.get("function_version"),
            duration_ms=doc.get("duration_ms"),
            params=doc.get("params"),
            endpoint_id=doc.get("endpoint_id"),
            created_at=doc.get("created_at"),
        )
