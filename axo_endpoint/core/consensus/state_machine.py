from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional, Tuple

from axo_endpoint.core.consensus.elector import LeaderView


@dataclass(frozen=True)
class ClusterState:
    """Everything that must survive node failure: membership/leader metadata,
    plus a snapshot of function-registry, data-registry, and bucket-registry
    entries.

    ``functions``/``data`` hold opaque serialized blobs ("name:version" ->
    bytes) not live FunctionRecord/DataRecord objects, so core.consensus never
    depends on core.functions or core.data — layering stays one-directional.
    ``buckets`` is keyed by bucket name alone (no version -- buckets aren't
    versioned).
    """

    term: int = 0
    leader_ids: FrozenSet[str] = field(default_factory=frozenset)
    members: FrozenSet[str] = field(default_factory=frozenset)
    functions: Dict[str, bytes] = field(default_factory=dict)
    data: Dict[str, bytes] = field(default_factory=dict)
    buckets: Dict[str, bytes] = field(default_factory=dict)
    version: int = 0


@dataclass(frozen=True)
class StateMutation:
    """A diff to fold into ClusterState."""

    function_changes: Dict[str, bytes] = field(default_factory=dict)
    data_changes: Dict[str, bytes] = field(default_factory=dict)
    bucket_changes: Dict[str, bytes] = field(default_factory=dict)
    leader_view: Optional[LeaderView] = None


class ReplicatedStateMachine(ABC):
    """Owns the authoritative, replicated view of ClusterState for this node.

    This is whole-state (or whole-diff) snapshot shipping, not a Raft-style
    committed log with an append index — deliberately the simple option.
    """

    @abstractmethod
    def snapshot(self) -> ClusterState:
        """Returns the current state (for sending to a follower, or local reads)."""

    @abstractmethod
    def apply_local(self, mutation: StateMutation) -> None:
        """Folds in a mutation produced locally (e.g. this node, as leader, just
        registered a function)."""

    @abstractmethod
    def apply_remote(self, incoming: ClusterState) -> bool:
        """Folds in a state snapshot received from the leader.

        Returns True iff it actually changed anything (incoming.version > local.version).
        """


class InMemoryReplicatedStateMachine(ReplicatedStateMachine):
    """Process-local, dict-backed ReplicatedStateMachine. Not persisted across restarts."""

    def __init__(self) -> None:
        self._state = ClusterState()
        self._lock = threading.Lock()

    def snapshot(self) -> ClusterState:
        with self._lock:
            return self._state

    def apply_local(self, mutation: StateMutation) -> None:
        with self._lock:
            functions = dict(self._state.functions)
            functions.update(mutation.function_changes)
            data = dict(self._state.data)
            data.update(mutation.data_changes)
            buckets = dict(self._state.buckets)
            buckets.update(mutation.bucket_changes)
            leader_ids = self._state.leader_ids
            term = self._state.term
            if mutation.leader_view is not None:
                leader_ids = mutation.leader_view.leader_ids
                term = mutation.leader_view.term
            self._state = ClusterState(
                term=term,
                leader_ids=leader_ids,
                members=self._state.members,
                functions=functions,
                data=data,
                buckets=buckets,
                version=self._state.version + 1,
            )

    def apply_remote(self, incoming: ClusterState) -> bool:
        with self._lock:
            if incoming.version <= self._state.version:
                return False
            self._state = incoming
            return True


# ── Wire encoding helpers ──────────────────────────────────────────────────
#
# Each value in ``functions``/``function_changes`` is itself a UTF-8 JSON blob
# (produced by ``registry_sync.serialize_function_record``), so embedding it
# in an outer JSON structure only requires parsing it back to a dict first —
# no extra base64 layer needed on top of what's already inside the blob.


def encode_function_changes(function_changes: Dict[str, bytes]) -> bytes:
    """Encodes a diff of function changes for the STATE_SYNC_PUSH payload."""
    return json.dumps(
        {key: json.loads(blob.decode("utf-8")) for key, blob in function_changes.items()}
    ).encode("utf-8")


def decode_function_changes(payload: bytes) -> Dict[str, bytes]:
    """Decodes a STATE_SYNC_PUSH payload back into per-key serialized blobs."""
    if not payload:
        return {}
    decoded = json.loads(payload.decode("utf-8"))
    return {key: json.dumps(record_dict).encode("utf-8") for key, record_dict in decoded.items()}


def encode_data_changes(data_changes: Dict[str, bytes]) -> bytes:
    """Encodes a diff of data changes for the STATE_SYNC_PUSH payload.

    Deliberate duplicate of encode_function_changes rather than a shared
    generic helper -- two domains isn't enough signal to justify genericizing
    this, matching the same call on ClusterState/StateMutation themselves.
    """
    return json.dumps(
        {key: json.loads(blob.decode("utf-8")) for key, blob in data_changes.items()}
    ).encode("utf-8")


def decode_data_changes(payload: bytes) -> Dict[str, bytes]:
    """Decodes a STATE_SYNC_PUSH payload back into per-key serialized blobs."""
    if not payload:
        return {}
    decoded = json.loads(payload.decode("utf-8"))
    return {key: json.dumps(record_dict).encode("utf-8") for key, record_dict in decoded.items()}


def encode_bucket_changes(bucket_changes: Dict[str, bytes]) -> bytes:
    """Encodes a diff of bucket changes for the STATE_SYNC_PUSH payload.

    Deliberate duplicate of encode_data_changes/encode_function_changes
    rather than a shared generic helper -- same reasoning as those two.
    """
    return json.dumps(
        {key: json.loads(blob.decode("utf-8")) for key, blob in bucket_changes.items()}
    ).encode("utf-8")


def decode_bucket_changes(payload: bytes) -> Dict[str, bytes]:
    """Decodes a STATE_SYNC_PUSH payload back into per-key serialized blobs."""
    if not payload:
        return {}
    decoded = json.loads(payload.decode("utf-8"))
    return {key: json.dumps(record_dict).encode("utf-8") for key, record_dict in decoded.items()}


def encode_state_changes(
    function_changes: Dict[str, bytes], data_changes: Dict[str, bytes], bucket_changes: Dict[str, bytes],
) -> bytes:
    """Combines all three domains' diffs into the single payload frame a
    STATE_SYNC_PUSH command carries -- a fixed 3-field combiner, not a
    generic domain map, so encode_function_changes/encode_data_changes/
    encode_bucket_changes stay independently simple and testable."""
    return json.dumps(
        {
            "functions": {key: json.loads(blob.decode("utf-8")) for key, blob in function_changes.items()},
            "data": {key: json.loads(blob.decode("utf-8")) for key, blob in data_changes.items()},
            "buckets": {key: json.loads(blob.decode("utf-8")) for key, blob in bucket_changes.items()},
        }
    ).encode("utf-8")


def decode_state_changes(payload: bytes) -> Tuple[Dict[str, bytes], Dict[str, bytes], Dict[str, bytes]]:
    """Decodes a STATE_SYNC_PUSH payload back into
    (function_changes, data_changes, bucket_changes)."""
    if not payload:
        return {}, {}, {}
    d = json.loads(payload.decode("utf-8"))
    functions = {key: json.dumps(v).encode("utf-8") for key, v in d.get("functions", {}).items()}
    data = {key: json.dumps(v).encode("utf-8") for key, v in d.get("data", {}).items()}
    buckets = {key: json.dumps(v).encode("utf-8") for key, v in d.get("buckets", {}).items()}
    return functions, data, buckets


def encode_cluster_state(state: ClusterState) -> bytes:
    """Encodes a full ClusterState snapshot for a STATE_SYNC_PULL reply."""
    return json.dumps(
        {
            "term": state.term,
            "leader_ids": list(state.leader_ids),
            "members": list(state.members),
            "functions": {
                key: json.loads(blob.decode("utf-8")) for key, blob in state.functions.items()
            },
            "data": {
                key: json.loads(blob.decode("utf-8")) for key, blob in state.data.items()
            },
            "buckets": {
                key: json.loads(blob.decode("utf-8")) for key, blob in state.buckets.items()
            },
            "version": state.version,
        }
    ).encode("utf-8")


def decode_cluster_state(payload: bytes) -> ClusterState:
    """Decodes a STATE_SYNC_PULL reply payload back into a ClusterState."""
    d = json.loads(payload.decode("utf-8"))
    return ClusterState(
        term=d["term"],
        leader_ids=frozenset(d["leader_ids"]),
        members=frozenset(d["members"]),
        functions={key: json.dumps(v).encode("utf-8") for key, v in d["functions"].items()},
        data={key: json.dumps(v).encode("utf-8") for key, v in d.get("data", {}).items()},
        buckets={key: json.dumps(v).encode("utf-8") for key, v in d.get("buckets", {}).items()},
        version=d["version"],
    )
