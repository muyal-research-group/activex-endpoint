from __future__ import annotations

from typing import Any, Dict, Optional

from axo_vem.domain.data.bucket import DataBucket
from axo_vem.domain.data.data_item import DataItem
from axo_vem.domain.data.repository import BucketRepository, DataItemRepository
from axo_vem.domain.events import models
from axo_vem.infrastructure.transport.ws.broadcaster import Broadcaster

BUCKET_EVENT_TYPES = frozenset({
    models.DATA_BUCKET_CREATED, models.DATA_REGISTERED, models.DATA_UPLOAD_COMPLETED, models.DATA_DELETED,
})

_WS_TOPIC = "buckets"


def _bucket_of(name: str) -> str:
    """"name" follows the "{bucket}/{key}" convention when registered into a
    bucket -- falls back to the bare name for unbucketed data, same
    derivation domain/events/stream_naming.py uses for the Kurrent stream."""
    return name.split("/", 1)[0] if "/" in name else name


def apply(
    bucket_repository: BucketRepository, data_item_repository: DataItemRepository,
    event_type: str, data: Dict[str, Any], broadcaster: Optional[Broadcaster] = None,
) -> None:
    """DataBucketCreated creates the bucket read-model doc; DataRegistered
    creates one DataItem doc (status="pending", the instant metadata
    registers -- before any chunk has necessarily arrived) keyed by
    name+version; DataUploadCompleted later flips that same doc to
    status="ready" once every chunk is confirmed present on the reporting
    node. DataRegistered is self-contained (unlike Job*'s fetch-then-mutate
    pattern) so it's a straight one-shot upsert; DataUploadCompleted only
    carries name/version, so it's a targeted status-only update instead.

    DataDeleted removes the DataItem doc entirely (the node-side deletion is
    itself replicated cluster-wide, so this read-model removal is the
    correct terminal state, not a soft-delete).

    DataRegistered/DataUploadCompleted/DataDeleted also broadcast a small
    status message over the shared WS broadcaster's "buckets" topic, right
    alongside the Mongo write -- not a second Kurrent subscription, just
    fanning the already-decoded event out to a second sink. See the plan
    this was built from for why that matters (avoids two consumers of the
    same stream that could drift out of sync)."""
    if event_type == models.DATA_BUCKET_CREATED:
        bucket_repository.save(DataBucket(
            name=data["name"], quota_bytes=data["quota_bytes"], created_at=data["created_at"],
        ))
    elif event_type == models.DATA_REGISTERED:
        data_item_repository.save(DataItem(
            name=data["name"], version=data["version"], format=data["format"],
            kind=data["kind"], total_size=data["total_size"], total_chunks=data["total_chunks"],
            status="pending",
        ))
        if broadcaster is not None:
            # Full item shape, not just the name/version/status triple the
            # other two branches broadcast -- this may be the *only* signal
            # a client ever sees for a brand new row (axo-ui no longer
            # refetches after upload), so it has to be enough to render one
            # on its own, not just flip an already-rendered row's status.
            broadcaster.broadcast(_WS_TOPIC, {
                "bucket": _bucket_of(data["name"]), "name": data["name"], "version": data["version"],
                "format": data["format"], "kind": data["kind"],
                "total_size": data["total_size"], "total_chunks": data["total_chunks"],
                "status": "pending",
            })
    elif event_type == models.DATA_UPLOAD_COMPLETED:
        data_item_repository.set_status(data["name"], data["version"], "ready")
        if broadcaster is not None:
            broadcaster.broadcast(_WS_TOPIC, {
                "bucket": _bucket_of(data["name"]), "name": data["name"],
                "version": data["version"], "status": "ready",
            })
    elif event_type == models.DATA_DELETED:
        data_item_repository.delete(data["name"], data["version"])
        if broadcaster is not None:
            broadcaster.broadcast(_WS_TOPIC, {
                "bucket": _bucket_of(data["name"]), "name": data["name"],
                "version": data["version"], "status": "deleted",
            })
