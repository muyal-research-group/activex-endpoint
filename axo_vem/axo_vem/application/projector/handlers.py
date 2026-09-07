from __future__ import annotations

from dataclasses import dataclass

from axo_vem.domain.choreography.repository import ChoreographyRepository
from axo_vem.domain.compute.consensus_recorder import ConsensusRecorder
from axo_vem.domain.compute.repository import EndpointRepository, FunctionRepository
from axo_vem.domain.data.repository import BucketRepository, DataItemRepository
from axo_vem.domain.events.activity_recorder import ActivityRecorder
from axo_vem.domain.execution.repository import JobRepository
from axo_vem.domain.identity.repository import UserProfileRepository
from axo_vem.domain.workspace.repository import VirtualEnvironmentRepository


@dataclass(frozen=True)
class ProjectorHandlers:
    """Bundles every abstract port the projector's dispatch needs -- one per
    read-model aggregate, matching the migration plan's per-aggregate
    application/projector/*_handler.py split. Replaces
    projector/upserts.py's former ProjectorCollections (which bundled raw
    pymongo Collections instead of domain-typed repositories)."""

    activity_recorder: ActivityRecorder
    user_profile_repository: UserProfileRepository
    virtual_environment_repository: VirtualEnvironmentRepository
    endpoint_repository: EndpointRepository
    function_repository: FunctionRepository
    consensus_recorder: ConsensusRecorder
    job_repository: JobRepository
    bucket_repository: BucketRepository
    data_item_repository: DataItemRepository
    choreography_repository: ChoreographyRepository
