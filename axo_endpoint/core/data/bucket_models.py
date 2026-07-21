from __future__ import annotations

from dataclasses import dataclass

# Distinct from DATA_REGISTERED_EVENT on purpose, same reasoning as that
# event's own docstring: core.consensus.bucket_sync.BucketRegistrySyncBridge
# is subscribed to this literal string and expects payload["name"]/
# payload["quota_bytes"] -- a shared event name would risk cross-firing the
# wrong sync bridge on a payload shape it doesn't expect.
BUCKET_REGISTERED_EVENT = "BUCKET_REGISTERED"


@dataclass(frozen=True)
class DataBucket:
    """A named, quota-enforced namespace to register data into.

    Not versioned (unlike DataRecord/FunctionRecord) -- a bucket is a
    long-lived container, not a point-in-time artifact. DataRecord.name
    becomes "{bucket}/{key}" by convention once registered into one; this
    dataclass itself carries no reference back to the DataRecords inside it,
    the same way FunctionRegistry doesn't track "who points at me."
    """

    name: str
    quota_bytes: int
    created_at: float
