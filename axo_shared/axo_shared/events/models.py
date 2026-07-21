from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventEnvelope(BaseModel):
    """Base fields every taxonomy event carries. Concrete events subclass this
    directly -- no per-domain intermediate base, since every field here is
    genuinely universal (even UserProfile/VirtualEnvironment events, which
    never travel the ZMQ envelope, still want event_id/created_at for
    Kurrent's own event metadata). A field being irrelevant for a given
    domain (e.g. runtime_type=None on a LeaderElected) is normal."""

    model_config = {"frozen": True}

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=_utcnow)
    user_id: Optional[str] = None
    virtual_environment_id: Optional[str] = None
    endpoint_id: Optional[str] = None
    runtime_type: Optional[Literal["process", "container"]] = None


class FailureDetail(BaseModel):
    """Embedded on every *Failed event. Field names deliberately mirror
    axo_shared.errors.AxoError.to_dict()'s keys so a FailureDetail can be
    built directly off any caught AxoError via from_axo_error, not
    reinvented per call site."""

    model_config = {"frozen": True}

    error_class: str
    error_code: int
    component: str
    message: str
    traceback: Optional[str] = None
    is_transient: bool = False

    @classmethod
    def from_axo_error(
        cls,
        err: "AxoError",  # noqa: F821 -- forward ref, avoids a hard axo_shared.errors import cycle
        component: str,
        is_transient: bool = False,
        traceback: Optional[str] = None,
    ) -> "FailureDetail":
        return cls(
            error_class=err.name,
            error_code=err.code,
            component=component,
            message=err.message,
            traceback=traceback,
            is_transient=is_transient,
        )


# ── Endpoint infrastructure ────────────────────────────────────────────────
# EndpointDeployed/Failed have no natural emission point in this codebase --
# nothing here "deploys" an endpoint, that's an external actor's action --
# so they're defined for taxonomy completeness only, never published.
ENDPOINT_DEPLOYED = "EndpointDeployed"
ENDPOINT_DEPLOY_FAILED = "EndpointDeployFailed"
ENDPOINT_STARTED = "EndpointStarted"
ENDPOINT_METRICS_REPORTED = "EndpointMetricsReported"
ENDPOINT_STOPPED = "EndpointStopped"
ENDPOINT_UNREACHABLE = "EndpointUnreachable"
ENDPOINT_RECOVERED = "EndpointRecovered"


class EndpointDeployed(EventEnvelope):
    """Defined for taxonomy completeness -- never published (see module note)."""


class EndpointDeployFailed(EventEnvelope):
    """Defined for taxonomy completeness -- never published (see module note)."""

    failure: FailureDetail


class EndpointStarted(EventEnvelope):
    """Published once by an endpoint at startup, if AXO_ENDPOINT_API_URI is configured."""

    router_bind: str
    pub_bind: str


class EndpointMetricsReported(EventEnvelope):
    """Published periodically (piggybacked on the heartbeat loop). ``metrics``
    is App._collect_metrics()'s dict verbatim."""

    metrics: Dict[str, Any] = Field(default_factory=dict)


class EndpointStopped(EventEnvelope):
    """Published on graceful shutdown (App.stop())."""

    uptime_ms: float


class EndpointUnreachable(EventEnvelope):
    """Published by axo_vem's EndpointLivenessWorker (not by axo_endpoint
    itself -- a dead/partitioned node can't report its own death) when a
    `running` endpoint's last-seen timestamp goes stale and a direct PING
    to it fails. last_seen_at is a snapshot of the endpoint's own
    last-known-seen timestamp at the moment this fired -- audit context for
    how stale the node already was, not re-derived later."""

    last_seen_at: Optional[str] = None


class EndpointRecovered(EventEnvelope):
    """Published by EndpointLivenessWorker when a previously `unreachable`
    endpoint answers PING successfully again. endpoint_id comes from
    EventEnvelope; no extra fields needed, mirrors EndpointStopped's
    minimalism."""


# ── Cluster consensus ───────────────────────────────────────────────────────
# ClusterElectionInitiated/Failed: Bully's recompute() is a pure, synchronous,
# always-succeeds function -- there's no real "initiated" phase distinct from
# the result, and no failure mode to report. Defined for completeness only,
# never published.
CLUSTER_ELECTION_INITIATED = "ClusterElectionInitiated"
CLUSTER_ELECTION_FAILED = "ClusterElectionFailed"
LEADER_ELECTED = "LeaderElected"
CONSENSUS_VIEW_CHANGED = "ConsensusViewChanged"
CLUSTER_QUORUM_LOST = "ClusterQuorumLost"
CLUSTER_QUORUM_RESTORED = "ClusterQuorumRestored"
CLUSTER_DEGRADED = "ClusterDegraded"


class ClusterElectionInitiated(EventEnvelope):
    """Defined for taxonomy completeness -- never published (see module note)."""


class ClusterElectionFailed(EventEnvelope):
    """Defined for taxonomy completeness -- never published (see module note)."""

    failure: FailureDetail


class LeaderElected(EventEnvelope):
    """Published by an endpoint when its own BullyLeaderElector's term changes."""

    leader_ids: List[str]
    term: int


class ConsensusViewChanged(EventEnvelope):
    """Published by an endpoint whenever its own leader/follower role flips."""

    term: int
    was_leader: bool
    is_leader: bool
    leader_ids: List[str]


class ClusterQuorumLost(EventEnvelope):
    """Live member count (self + peers) dropped below the derived quorum size."""

    term: int
    member_count: int
    quorum_size: int


class ClusterQuorumRestored(EventEnvelope):
    """Live member count recovered back to/above the derived quorum size."""

    term: int
    member_count: int
    quorum_size: int


class ClusterDegraded(EventEnvelope):
    """A peer was evicted but the cluster still holds quorum."""

    term: int
    member_count: int
    quorum_size: int
    evicted_peer_id: str


# ── Function lifecycle ──────────────────────────────────────────────────────
FUNCTION_REGISTERED = "FunctionRegistered"
FUNCTION_REGISTER_FAILED = "FunctionRegisterFailed"
FUNCTION_BUILD_STARTED = "FunctionBuildStarted"
FUNCTION_BUILD_COMPLETED = "FunctionBuildCompleted"
FUNCTION_BUILD_FAILED = "FunctionBuildFailed"
FUNCTION_DEPLOYED = "FunctionDeployed"
FUNCTION_DEPLOY_FAILED = "FunctionDeployFailed"
FUNCTION_ACTIVATED = "FunctionActivated"
FUNCTION_DEACTIVATED = "FunctionDeactivated"
FUNCTION_UPDATED = "FunctionUpdated"
FUNCTION_STOPPED = "FunctionStopped"
FUNCTION_CRASHED = "FunctionCrashed"
FUNCTION_DELETED = "FunctionDeleted"
FUNCTION_DELETE_FAILED = "FunctionDeleteFailed"
FUNCTION_ENDPOINT_DETACHED = "FunctionEndpointDetached"


class FunctionRegistered(EventEnvelope):
    """Published when a function is first registered. ``runtime_spec`` is
    RuntimeSpec.to_dict(), never the function code itself. ``params_schema``
    is params_schema_to_list(...), or empty/None for a function that accepts
    an arbitrary, unvalidated params blob. ``name`` is the caller-given
    display name (function_id is a content-derived hash of
    (user_id, virtual_environment_id, name), never human-readable) -- carried
    only on this event since the read-model projector does a $set merge, so
    it persists on the doc for the rest of that function_id/version's life
    without every later lifecycle event needing to repeat it."""

    function_id: str
    version: int
    name: Optional[str] = None
    runtime_spec: Optional[Dict[str, Any]] = None
    params_schema: Optional[List[Dict[str, Any]]] = None
    owner_user_id: Optional[str] = None


class FunctionRegisterFailed(EventEnvelope):
    function_id: str
    version: int
    failure: FailureDetail


class FunctionBuildStarted(EventEnvelope):
    """Published around ContainerSummoner.build_runner_image() -- only fires
    for container-runtime functions needing a fresh per-Python-version base
    image build. ``function_id`` is None for the (normal, shared) case of a
    generic base-image build not tied to one function."""

    function_id: Optional[str] = None
    python_version: str
    image_tag: str


class FunctionBuildCompleted(EventEnvelope):
    function_id: Optional[str] = None
    python_version: str
    image_tag: str
    duration_ms: float


class FunctionBuildFailed(EventEnvelope):
    function_id: Optional[str] = None
    python_version: str
    image_tag: str
    failure: FailureDetail


class FunctionDeployed(EventEnvelope):
    """A worker/container is being (re)provisioned for this function
    (FunctionState.COLD_START, or a container SPAWNED/READY)."""

    function_id: str
    version: int


class FunctionDeployFailed(EventEnvelope):
    function_id: str
    version: int
    failure: FailureDetail


class FunctionActivated(EventEnvelope):
    """A worker/container just began executing a job (FunctionState.RUNNING)."""

    function_id: str
    version: int
    job_id: str


class FunctionDeactivated(EventEnvelope):
    """A worker/container finished running (FunctionState.COMPLETED/FAILED).
    Job-level outcome lives on the Job* events, not duplicated here --
    ``state`` is kept only as a filtering hint."""

    function_id: str
    version: int
    state: str


class FunctionUpdated(EventEnvelope):
    """An existing version's params_schema/env_vars was mutated in place --
    no new version, no code change. Carries the record's full current
    (post-merge) values, not just whatever fields this update touched.
    Takes effect lazily: an already-running worker/container keeps its old
    config until it next naturally redeploys."""

    function_id: str
    version: int
    params_schema: Optional[List[Dict[str, Any]]] = None
    env_vars: Optional[Dict[str, str]] = None


class FunctionStopped(EventEnvelope):
    """A worker/container was evicted gracefully -- the idle-TTL/
    max-invocations sweep, or an explicit dismissal. Never fires for a crash
    (see FunctionCrashed) -- this is the routine/graceful teardown family."""

    function_id: str
    version: int
    reason: Literal["idle_ttl", "max_invocations", "dismissed"]


class FunctionCrashed(EventEnvelope):
    """A worker process died unexpectedly (ungraceful exit), distinct from
    the routine FunctionStopped teardown family. Currently only ever fires
    for the process runtime -- container mid-run crash/OOM detection has no
    monitoring mechanism yet and is explicitly out of scope for now."""

    function_id: str
    version: int


class FunctionDeleted(EventEnvelope):
    function_id: str
    version: int


class FunctionDeleteFailed(EventEnvelope):
    function_id: str
    version: int
    failure: FailureDetail


class FunctionEndpointDetached(EventEnvelope):
    """One endpoint (this event's inherited ``endpoint_id``) no longer holds
    this function version -- e.g. PurgeEndpointUseCase purging a node that
    was one of several replicas. Distinct from FunctionDeleted: the function
    itself is still alive, just with one fewer entry in its endpoint_id
    list. Only ever appended directly by axo_vem (mirrors FunctionDeleted's
    own PurgeEndpointUseCase-authored path) -- axo_endpoint never emits this
    since it has no notion of "detach," only replicate/tombstone."""

    function_id: str
    version: int


# ── Job pipeline ─────────────────────────────────────────────────────────────
JOB_QUEUED = "JobQueued"
JOB_STARTED = "JobStarted"
JOB_COMPLETED = "JobCompleted"
JOB_FAILED = "JobFailed"


class JobQueued(EventEnvelope):
    """A job was accepted for execution (existing JOB_SUBMITTED bus event,
    renamed for past-tense consistency). ``version`` matches every other
    event carrying a function_id (FunctionRegistered, FunctionDeployed, ...)
    -- previously named ``function_version`` here and on JobStarted, the one
    inconsistency in an otherwise uniform "version" naming across this
    taxonomy."""

    job_id: str
    function_id: str
    version: Optional[int] = None
    params: Optional[Dict[str, Any]] = None


class JobStarted(EventEnvelope):
    """A worker/container actually picked the job up and began executing it
    -- distinct from JobQueued (accepted) since a job may sit behind a
    cold-starting worker for a while first. version/params mirror
    JobQueued's -- carried again here (not just there) because the version
    that actually picked up the job is the one that matters for correctness
    (see ExternalEventForwardingBridge, which trusts this field instead of
    re-deriving "latest registered version" from the function registry)."""

    job_id: str
    function_id: str
    version: Optional[int] = None
    params: Optional[Dict[str, Any]] = None


class JobCompleted(EventEnvelope):
    job_id: str
    function_id: str
    duration_ms: Optional[float] = None


class JobFailed(EventEnvelope):
    job_id: str
    function_id: str
    failure: FailureDetail
    duration_ms: Optional[float] = None


# ── Data & buckets ───────────────────────────────────────────────────────────
DATA_BUCKET_CREATED = "DataBucketCreated"
DATA_REGISTERED = "DataRegistered"
DATA_UPLOAD_COMPLETED = "DataUploadCompleted"
DATA_DELETED = "DataDeleted"


class DataBucketCreated(EventEnvelope):
    """A named, quota-enforced namespace was registered on one node --
    mirrors FunctionRegistered's shape for the "declare metadata ahead of
    use" pattern, just for buckets instead of functions."""

    name: str
    quota_bytes: int


class DataRegistered(EventEnvelope):
    """One piece of data's metadata was declared via DATA_REGISTER. ``name``
    follows the "{bucket}/{key}" convention when registered into a bucket,
    or is a bare name for unbucketed data -- no separate bucket field."""

    name: str
    version: int
    format: str
    kind: str
    total_size: int
    total_chunks: int


class DataUploadCompleted(EventEnvelope):
    """Every chunk of a previously-DataRegistered record is now present on
    the reporting node -- the read-model signal that flips a DataItem from
    "pending" to "ready". Deliberately thin (just the same name/version key
    DataRegistered used) since nothing consuming this needs more."""

    name: str
    version: int


class DataDeleted(EventEnvelope):
    """A previously-registered data record was removed (DATA_DELETE) --
    drives removing the DataItem read-model row. Deliberately thin, same
    reasoning as DataUploadCompleted."""

    name: str
    version: int


# ── User profile ─────────────────────────────────────────────────────────────
# UserProfile events never travel through the ZMQ envelope/wire path -- they
# originate inside axo_vem's own process (an HTTP request handler),
# not on a remote axo_endpoint node, so they're appended to Kurrent directly.
USER_PROFILE_CREATED = "UserProfileCreated"
USER_PROFILE_CREATION_FAILED = "UserProfileCreationFailed"
USER_PROFILE_UPDATED = "UserProfileUpdated"
USER_PROFILE_DELETED = "UserProfileDeleted"
# Username/email live in Xolo (external auth), not this domain's storage --
# these two are defined for taxonomy completeness only, never published,
# until Xolo integration threads the underlying data through.
USER_PROFILE_USERNAME_UPDATED = "UserProfileUsernameUpdated"
USER_PROFILE_EMAIL_UPDATED = "UserProfileEmailUpdated"


class Preferences(BaseModel):
    """UI-facing user settings, grouped separately from UserProfile's
    identity-ish fields so future settings of this kind have one obvious
    place to go instead of accumulating as more top-level fields."""

    model_config = {"frozen": True}

    color: Optional[str] = None
    view_mode: str = "list"
    language: str = "en"
    # Default time window (in minutes) the activity/events feed shows for
    # this user -- purely a display default, bounded by whatever
    # AXO_VEM_ACTIVITY_RETENTION_HOURS still actually retains
    # server-side (see infrastructure/api/controllers/history.py and the
    # activity retention worker on the axo_vem side).
    activity_window_minutes: int = 60
    # Minutes an endpoint must have been `unreachable` past which axo-ui
    # surfaces the purge action prominently for this viewer. Purely a
    # UI-surfacing default -- never enforced as a second backend purge gate
    # (see infrastructure/transport/api/controllers/endpoints.py's
    # purge_endpoint route, axo_vem side).
    endpoint_purge_eligible_after_minutes: int = 60


class UserProfileCreated(EventEnvelope):
    profile_photo: str
    preferences: Preferences


class UserProfileCreationFailed(EventEnvelope):
    """Published when Xolo signup succeeded (an external identity now
    exists) but persisting the corresponding local UserProfile failed --
    an audit trail for identities that exist upstream without a local
    profile yet, not a taxonomy-completeness placeholder like
    UserProfileUsernameUpdated/UserProfileEmailUpdated above."""

    failure: FailureDetail


class UserProfileUpdated(EventEnvelope):
    profile_photo: str
    preferences: Preferences


class UserProfileDeleted(EventEnvelope):
    """user_id comes from EventEnvelope."""


class UserProfileUsernameUpdated(EventEnvelope):
    """Defined for taxonomy completeness -- never published (see module note)."""

    new_username: str


class UserProfileEmailUpdated(EventEnvelope):
    """Defined for taxonomy completeness -- never published (see module note)."""

    new_email: str


# ── Virtual environment / namespace assignment ──────────────────────────────
VIRTUAL_ENV_CREATED = "VirtualEnvironmentCreated"
VIRTUAL_ENV_UPDATED = "VirtualEnvironmentUpdated"
VIRTUAL_ENV_DELETED = "VirtualEnvironmentDeleted"
# An endpoint being (re)assigned to, or removed from, a VirtualEnvironment --
# always self-reported by the endpoint itself after VIRTUAL_ENV_ASSIGN
# succeeds or clears its assignment.
ENDPOINT_VIRTUAL_ENV_ASSIGNED = "EndpointVirtualEnvironmentAssigned"
ENDPOINT_VIRTUAL_ENV_DETACHED = "EndpointVirtualEnvironmentDetached"
# Audit-only: appended by axo_vem's projector itself (not forwarded by any
# endpoint) whenever a LeaderElected/ConsensusViewChanged resolves to a new
# mesh leader belonging to this VE. The read-model leader_endpoint_id field is
# updated immediately by that same projector step -- this event never gets
# waited on, it just gives that change a permanent, replayable record.
VIRTUAL_ENV_LEADER_CHANGED = "VirtualEnvironmentLeaderChanged"


class ResourceQuota(BaseModel):
    """Declared, not enforced -- bookkeeping only for now."""

    model_config = {"frozen": True}

    cpu: float
    ram: int
    disk: int


class VirtualEnvironmentCreated(EventEnvelope):
    virtual_environment_id: str
    name: str
    owner_user_id: str
    resource_quota: ResourceQuota


class VirtualEnvironmentUpdated(EventEnvelope):
    virtual_environment_id: str
    name: str
    resource_quota: ResourceQuota


class VirtualEnvironmentDeleted(EventEnvelope):
    virtual_environment_id: str


class EndpointVirtualEnvironmentAssigned(EventEnvelope):
    """endpoint_id + virtual_environment_id are both already on EventEnvelope."""


class EndpointVirtualEnvironmentDetached(EventEnvelope):
    previous_virtual_environment_id: str


class VirtualEnvironmentLeaderChanged(EventEnvelope):
    virtual_environment_id: str
    leader_endpoint_id: str
