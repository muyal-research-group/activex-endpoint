from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from axo_vem.domain.execution.job import Job


class JobRepository(ABC):
    """Write/read access for Job aggregates. Implemented by
    infrastructure/database/mongo/job_repository.py's MongoJobRepository;
    applied by the projector (application/projector/job_handler.py) after a
    Job* event lands in Kurrent."""

    @abstractmethod
    def get(self, job_id: str) -> Optional[Job]: ...

    @abstractmethod
    def list_by_function(self, function_id: str, function_version: Optional[int] = None) -> List[Job]: ...

    @abstractmethod
    def save(self, job: Job) -> None: ...
