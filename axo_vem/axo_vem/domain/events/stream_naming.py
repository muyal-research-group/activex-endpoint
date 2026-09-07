from __future__ import annotations

from typing import Any, Dict

from axo_vem.domain.events import models


def stream_name_for(event_type: str, endpoint_id: str, data: Dict[str, Any]) -> str:
    """Maps one taxonomy event to its Kurrent stream name, one stream per
    entity instance (<category>-<id>): endpoints-<endpoint_id>,
    functions-<function_id>-<version> (per-version -- see below),
    consensus-<endpoint_id> (per-observer -- every endpoint independently reports the
    same cluster fact, dedup happens at the projector), activity-<function_id>.

    Follows Kurrent's <category>-<id> convention so its built-in $ce-<category>
    system projection stays available for ops tooling later, though the
    projector itself does not depend on it.

    Function lifecycle events are keyed by <function_id>-<version>, not just
    <function_id> -- every version of one function used to share a single
    stream, which meant a hard-delete-on-purge for one version would have
    destroyed every sibling version's history too. Build events have no
    version field at all (they're not tied to one specific version), so they
    keep the coarser <function_id>-only (or shared-base-image) stream.

    This is axo_vem-local domain knowledge (which stream an event
    belongs to), not shared with axo_endpoint, so it lives in this project's
    own domain layer rather than in axo_shared.
    """
    if event_type in (
        models.ENDPOINT_STARTED, models.ENDPOINT_METRICS_REPORTED, models.ENDPOINT_STOPPED,
        models.ENDPOINT_UNREACHABLE, models.ENDPOINT_RECOVERED,
        models.ENDPOINT_VIRTUAL_ENV_ASSIGNED, models.ENDPOINT_VIRTUAL_ENV_DETACHED,
    ):
        return f"endpoints-{endpoint_id}"
    if event_type in (
        models.FUNCTION_REGISTERED, models.FUNCTION_REGISTER_FAILED,
        models.FUNCTION_DEPLOYED, models.FUNCTION_DEPLOY_FAILED,
        models.FUNCTION_ACTIVATED, models.FUNCTION_DEACTIVATED,
        models.FUNCTION_UPDATED,
        models.FUNCTION_STOPPED, models.FUNCTION_CRASHED,
        models.FUNCTION_DELETED, models.FUNCTION_DELETE_FAILED,
        models.FUNCTION_ENDPOINT_DETACHED,
    ):
        return f"functions-{data['function_id']}-{data['version']}"
    if event_type in (models.FUNCTION_BUILD_STARTED, models.FUNCTION_BUILD_COMPLETED, models.FUNCTION_BUILD_FAILED):
        # function_id is None for a shared per-Python-version base image
        # build not tied to one function -- fall back to a stream keyed by
        # python_version instead.
        function_id = data.get("function_id")
        return f"functions-{function_id}" if function_id else f"functions-base-image-py{data['python_version']}"
    if event_type in (
        models.LEADER_ELECTED, models.CONSENSUS_VIEW_CHANGED,
        models.CLUSTER_QUORUM_LOST, models.CLUSTER_QUORUM_RESTORED, models.CLUSTER_DEGRADED,
    ):
        return f"consensus-{endpoint_id}"
    if event_type in (models.JOB_QUEUED, models.JOB_STARTED, models.JOB_COMPLETED, models.JOB_FAILED):
        return f"activity-{data['function_id']}"
    if event_type == models.DATA_BUCKET_CREATED:
        return f"buckets-{data['name']}"
    if event_type in (models.DATA_REGISTERED, models.DATA_UPLOAD_COMPLETED, models.DATA_DELETED):
        # "name" follows the "{bucket}/{key}" convention when registered
        # into a bucket -- fall back to the bare name itself for unbucketed
        # data, giving it its own single-item stream.
        bucket = data["name"].split("/", 1)[0] if "/" in data["name"] else data["name"]
        return f"buckets-{bucket}"
    raise ValueError(f"unknown event_type: {event_type!r}")
