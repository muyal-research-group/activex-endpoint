from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Distinct from FunctionState.REGISTERED.value ("REGISTERED") on purpose --
# core.consensus.registry_sync.RegistrySyncBridge.on_function_event is
# subscribed to that literal string and expects payload["function_id"]; if
# DataRegistry emitted under the same string it would fire that handler too
# and crash on a missing "function_id" key (data events carry "data_id").
DATA_REGISTERED_EVENT = "DATA_REGISTERED"

# Fired once, the moment every chunk of a registered record is present on
# this node (StorageBackend.exists() true for every index) -- the signal
# axo_vem's bucket read model uses to flip a DataItem from
# "pending" to "ready". Distinct from DATA_REGISTERED_EVENT (metadata only,
# fires before any chunk is uploaded) for the same reason DATA_REGISTERED_EVENT
# is distinct from FunctionState.REGISTERED -- a dedicated string so nothing
# else on the bus mistakes one for the other.
DATA_UPLOAD_COMPLETED_EVENT = "DATA_UPLOAD_COMPLETED"

# Fired once a DataRecord and its chunks have been removed from this node's
# catalog/storage via DataRegistry.delete().
DATA_DELETED_EVENT = "DATA_DELETED"


@dataclass(frozen=True)
class DataRecord:
    """The metadata for one piece of registered data, at one version.

    Never mutated after creation -- registering a new version creates a new
    record. Chunk bytes themselves live separately in a storage backend,
    keyed via core.data.chunking.chunk_key; this record only carries the
    shape needed to address and validate them. declared_hash is whatever the
    writer (client or a finalize_stream call) computed over the whole
    payload before/at the moment of registration -- it's the same on every
    node once replicated, unlike a locally-computed hash, which is why it's
    not paired with a "verified" flag here (that's node-local status, see
    DataRegistry.status()/DataStatus).
    """

    name: str
    version: int
    alias: str
    format: str   # dataio Format name, e.g. "raw"/"pickle"/"csv"/"npy"
    kind: str     # storage backend kind, e.g. "fs"
    total_size: int
    chunk_bytes: int
    total_chunks: int
    created_at: float
    declared_hash: Optional[str] = None
    content_hash_algo: str = "sha256"


@dataclass(frozen=True)
class DataStatus:
    """Node-local truth about one (name, version): what the replicated
    DataRecord declares, plus what this node's own storage backend actually
    has on disk right now. Never replicated itself -- recomputed per node,
    per query."""

    registered: bool
    name: str
    version: int
    format: str
    kind: str
    total_size: int
    chunk_bytes: int
    total_chunks: int
    present_chunk_indices: list
    complete: bool
    progress_ratio: float
    declared_hash: Optional[str]
    computed_hash: Optional[str]
    hash_verified: Optional[bool]
