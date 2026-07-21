from __future__ import annotations

from typing import Any, Dict

from axo_vem.domain.events import models
from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository
from axo_vem.domain.workspace.virtual_environment import VirtualEnvironment, capacity_from_quota_dict


def apply(repository: VirtualEnvironmentRepository, event_type: str, data: Dict[str, Any]) -> None:
    """VirtualEnvironmentCreated carries the full aggregate shape (including
    owner_user_id); VirtualEnvironmentUpdated deliberately omits
    owner_user_id (ownership is immutable after creation), so applying an
    Updated event first fetches the existing aggregate to preserve its
    owner_user_id rather than losing it -- get()/save() replaces
    projector/upserts.py's former plain-$set upsert_virtual_environment,
    which relied on Mongo's partial-$set semantics to achieve the same
    effect. soft_delete() replaces the former soft_delete_virtual_environment."""
    if event_type == models.VIRTUAL_ENV_CREATED:
        virtual_environment = VirtualEnvironment(
            virtual_environment_id=data["virtual_environment_id"],
            name=data["name"],
            owner_user_id=data["owner_user_id"],
            capacity=capacity_from_quota_dict(data["resource_quota"]),
        )
        repository.save(virtual_environment)
    elif event_type == models.VIRTUAL_ENV_UPDATED:
        existing = repository.get(data["virtual_environment_id"])
        owner_user_id = existing.owner_user_id if existing is not None else data.get("owner_user_id")
        virtual_environment = VirtualEnvironment(
            virtual_environment_id=data["virtual_environment_id"],
            name=data["name"],
            owner_user_id=owner_user_id,
            capacity=capacity_from_quota_dict(data["resource_quota"]),
        )
        repository.save(virtual_environment)
    elif event_type == models.VIRTUAL_ENV_DELETED:
        repository.soft_delete(data["virtual_environment_id"], data["created_at"])
    elif event_type == models.VIRTUAL_ENV_LEADER_CHANGED:
        # Audit-only -- compute_handler already applied leader_endpoint_id
        # directly to the read model the moment the election was detected,
        # not by waiting for this event to replay. Recognized here purely so
        # the dispatcher's exhaustive event-type check doesn't reject it and
        # activity_recorder.record() (called unconditionally before this
        # branch) captures it in the VE's history feed.
        pass
