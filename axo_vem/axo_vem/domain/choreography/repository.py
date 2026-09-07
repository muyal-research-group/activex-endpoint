from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from axo_vem.domain.choreography.choreography import Choreography


class ChoreographyRepository(ABC):
    """Read/write access to Choreography aggregates. Writes are applied by
    the projector after an application use case appends a domain event to
    Kurrent -- see application/projector/choreography_handler.py.
    Soft-deleted choreographies (deleted_at set) are never returned by any
    read method here."""

    @abstractmethod
    def get(self, choreography_id: str) -> Optional[Choreography]: ...

    @abstractmethod
    def list(self, owner_user_id: Optional[str] = None) -> List[Choreography]: ...

    @abstractmethod
    def save(self, choreography: Choreography) -> None: ...

    @abstractmethod
    def soft_delete(self, choreography_id: str, deleted_at) -> None: ...
