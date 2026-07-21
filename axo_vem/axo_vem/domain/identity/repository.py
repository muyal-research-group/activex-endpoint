from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from axo_vem.domain.identity.user_profile import UserProfile


class UserProfileRepository(ABC):
    """Read/write access to UserProfile aggregates. Writes are applied by
    the projector after an application use case appends a domain event to
    Kurrent -- see application/projector/identity_handler.py."""

    @abstractmethod
    def get_by_user_id(self, user_id: str) -> Optional[UserProfile]: ...

    @abstractmethod
    def save(self, profile: UserProfile) -> None: ...

    @abstractmethod
    def delete(self, user_id: str) -> None: ...
