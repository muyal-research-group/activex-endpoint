from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from axo_vem.domain.choreography.run import ChoreographyRun


class ChoreographyRunRepository(ABC):
    """Read/write access to ChoreographyRun records -- a plain Mongo-backed
    store written directly by the orchestrator (RunChoreographyUseCase),
    not fed by the Kurrent projector (see ChoreographyRun's docstring)."""

    @abstractmethod
    def get(self, run_id: str) -> Optional[ChoreographyRun]: ...

    @abstractmethod
    def list_by_choreography(self, choreography_id: str) -> List[ChoreographyRun]: ...

    @abstractmethod
    def has_active_run(self, choreography_id: str) -> bool: ...

    @abstractmethod
    def save(self, run: ChoreographyRun) -> None: ...
