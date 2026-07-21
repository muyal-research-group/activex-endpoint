from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from axo_vem.domain.workspace.virtual_environment import VirtualEnvironment


class VirtualEnvironmentRepository(ABC):
    """Read/write access to VirtualEnvironment aggregates. Writes are
    applied by the projector after an application use case appends a domain
    event to Kurrent -- see application/projector/workspace_handler.py.
    Soft-deleted virtual environments (deleted_at set) are never returned by
    any read method here."""

    @abstractmethod
    def get(self, virtual_environment_id: str) -> Optional[VirtualEnvironment]: ...

    @abstractmethod
    def list(self, owner_user_id: Optional[str] = None) -> List[VirtualEnvironment]: ...

    @abstractmethod
    def search_by_name(self, name: str, owner_user_id: Optional[str] = None) -> List[VirtualEnvironment]: ...

    @abstractmethod
    def save(self, virtual_environment: VirtualEnvironment) -> None: ...

    @abstractmethod
    def soft_delete(self, virtual_environment_id: str, deleted_at) -> None: ...

    @abstractmethod
    def set_leader_endpoint_id(self, virtual_environment_id: str, leader_endpoint_id: str) -> None:
        """Narrow, conditional update (no upsert) -- only ever called by the
        projector's compute_handler once it has resolved a newly-elected
        mesh leader to one of this VE's assigned endpoints."""

    @abstractmethod
    def clear_leader_endpoint_id(self) -> None:
        """Unsets leader_endpoint_id on whichever VE currently holds it --
        there is only ever one mesh-wide leader at a time, so this always
        runs before set_leader_endpoint_id() picks the new one (a no-op if
        no VE currently has the field set)."""
