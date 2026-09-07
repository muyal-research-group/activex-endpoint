# Data registry / storage unification — design plan

Status: design agreed in conversation, no code written yet. Continue here.

## Goal

A no-code way for clients to register data (dataframes, matrices, files) ahead of a
job — analogous to how `FunctionRegistry` lets clients register function code — so a
later job can consume it via the existing, unchanged `dataio.read(IORef)` call.

Built on a single unified storage abstraction (`StorageBackend`) instead of the two
that exist today (`StorageBackend` in `core/storage/backend.py`, in-memory only;
`BlobBackend` in `core/dataio/backend.py`, FS-backed). The registered metadata should
replicate to follower nodes using the leader/follower consensus machinery that already
exists in `core/consensus/`.

## Decisions

### 1. `StorageKey` becomes abstract — one concrete `Key` type per backend

- `Key(ABC)` — thin abstract base. Needs a `to_str()` / per-kind `from_str()` codec
  contract (see #2) so `IORef.location` can round-trip through it.
- `StorageKey(id, version, alias)` — today's dataclass, unchanged. Used by
  `FunctionRegistry` and the new `DataRegistry`'s metadata catalog (logical/versioned
  stores).
- `FsKey(path)` — used by `FilesystemStorageBackend`.
- `ObjectKey(bucket, key, version_id=None)` — future `ObjectStorageBackend` (S3-style).

`StorageBackend` becomes `Generic[K, V]`, trimmed to `put`/`get`/`exists` only. The
id/version/alias convenience lookups (`get_by_id`, `get_by_alias_version`, etc.) move
off the shared abstract interface — they only make sense for `StorageKey`, not
`FsKey`/`ObjectKey`. Callers that want them (`FunctionRegistry`, `DataRegistry`'s
catalog) type against `StorageBackend[StorageKey, V]` specifically.

### 2. `BlobBackend` gets absorbed into `StorageBackend` — no wire change

`FilesystemStorageBackend(StorageBackend[FsKey, bytes])` replaces
`FilesystemBlobBackend`: same path-containment check (`os.path.realpath` +
`commonpath`), ported to operate on `FsKey.path`. Needs its own new `StorageError`
subtype for a traversal attempt, since that check is newly built into this backend.

**`IORef` does NOT extend/inherit `Key`.** It must stay one uniform,
wire-serializable shape (`kind`, `location`, `format` — all plain strings) because the
zmq/container transport JSON-encodes it generically (`IORef.to_dict/from_dict`,
`container_runtime.py` frame comment) without knowing which backend's key shape is
behind a given `kind` ahead of time. `format` is also a dataio-only client-side codec
concern, unrelated to addressing — folding it into `Key` would leak that concern into
the storage layer. Instead: composition, not inheritance. `Key` owns
`to_str()`/`from_str()`; `IORef.location` is always `key.to_str()`.
`resolve_io_request` becomes:

```
key = KEY_TYPES[ref.kind].from_str(ref.location)
storage_backends[ref.kind].get(key)
```

**No general `StorageError -> DataIOError` translation layer is needed.** Verified by
reading both transports (`process_runtime.py`, `container_runtime.py`): the io_reply
protocol does `str(result.unwrap_err())` on error, and the receiving side
(`worker_entry.py`, `runner/server.py`) rewraps that string into a fresh generic
`DataIOError` — the original exception's Python type is discarded before it crosses the
wire. Grepped the whole codebase: nothing anywhere branches on the specific
`IONotFoundError`/`IOBackendError`/`IOPathTraversalError` subtype; they exist only so
the raising site has a distinct `.code`/`.name` for structured logging. So
`resolve_io_request` can just propagate whatever `StorageError` the backend raises
as-is.

The one real adaptation needed: `StorageBackend.get()` returns `Ok(None)` for "not
found" (a valid non-error case for other callers, e.g. `FunctionRegistry.get`), but
dataio's `read()` must fail loudly on empty. So `resolve_io_request` still needs:
`Ok(None) -> Err(IONotFoundError(...))` for read ops specifically. That's the only
translation logic required — not a full hierarchy mapping.

(Separately, unrelated to the mid-job proxy path: the *synchronous* `CommandResult`
-based handlers, like the planned `DATA_REGISTER`, still do need to wrap backend errors
into a domain error — e.g. reusing `StorageFailureError` from `core/errors.py`, exactly
as `FunctionRegisterHandler` already does — because `CommandResult.error_code`/
`error_name` genuinely cross the wire there.)

### 3. `DataRegistry` — structurally identical to `FunctionRegistry`

Template: `core/functions/registry.py`.

- Small metadata catalog: `StorageBackend[StorageKey, DataRecord]` (in-memory today).
  `DataRecord{name, version, alias, format, kind, location, size, created_at}`, where
  `location` is the blob backend's key, string-encoded — i.e. exactly what goes into an
  `IORef.location`.
- Actual bytes: whatever `StorageBackend[K, bytes]` is registered for `kind` (`fs`
  today).
- `register(name, version, format, data, now)` writes bytes to the blob backend, writes
  the `DataRecord` to the catalog, and returns an `IORef` the client hands straight to a
  later job's `params`. `dataio.read(IORef)` needs zero changes to consume it.
- New synchronous wire op `DATA_REGISTER`, handled directly on the router thread (like
  `FUNCTION_REGISTER` — not queued, since it's registration, not job execution).

### 4. Metadata replication — extend the existing consensus pattern, don't generalize it

Template: `core/consensus/registry_sync.py` + `core/consensus/state_machine.py`.

Mirror `RegistrySyncBridge` with a `DataRegistrySyncBridge`:
- Add `data: Dict[str, bytes]` to `ClusterState`.
- Add `data_changes` to `StateMutation`.
- Add `mark_data_dirty` to `DirtyTracker`.
- Add `encode_data_changes`/`decode_data_changes` next to the function ones.

Deliberately a copy of the proven function-replication pattern rather than a generic
domain-map refactor (`Dict[str, Dict[str, bytes]]` keyed by domain name) — two domains
isn't enough signal to justify genericizing `ClusterState`. Revisit if a third
replicated-metadata domain shows up later.

### 5. Blob bytes replicate separately — throttled background push-stream

Chosen over lazy-pull-on-miss and a size-based hybrid, because the goal is followers
proactively staying warm/in-sync, not just reactively caching on first read.

- New wire op, e.g. `DATA_BLOB_STREAM` — chunked:
  `(data_id, version, chunk_index, total_chunks, chunk_bytes)`.
- Sent by a leader-only background loop, **separate** from the heartbeat-tick-driven
  consensus loop (`run_consensus_tick` in `service/consensus_loop.py`), so it can't
  starve the small/frequent metadata sync traffic.
- Paced by two new `AXO_ENDPOINT_*` config knobs: replication rate (bytes/sec) and
  chunk size. Remember: `Config` is the only env reader (`service/config.py` /
  `axo_endpoint/config.py`).
- Same dirty-marking trigger as metadata (`DataRegistrySyncBridge`) enqueues a
  per-follower blob-replication job when a `DataRecord` changes.
- Follower-side handler (analogous to `StateSyncPushHandler`) buffers incoming chunks
  and only commits to its local `StorageBackend[FsKey, bytes]` once `total_chunks` all
  arrive — so a job reading mid-transfer never sees a partial blob.

**Left open, decide at implementation time:**
- Resume behavior if the leader restarts or a follower reconnects mid-stream.
- Bounding a follower's pending-replication queue if datasets register faster than the
  throttle can drain them.

## Where to start when implementing

1. `core/storage/backend.py` — introduce `Key(ABC)`, keep `StorageKey` as the concrete
   logical implementation, trim `StorageBackend` to `Generic[K, V]` with just
   `put`/`get`/`exists`.
2. New `core/storage/filesystem.py` (or similar) — `FsKey` + `FilesystemStorageBackend`,
   porting the path-containment check from `core/dataio/backend.py`'s
   `FilesystemBlobBackend`.
3. `core/dataio/protocol.py` — rewrite `resolve_io_request` against
   `Dict[str, StorageBackend]` instead of `Dict[str, BlobBackend]`, add the
   `Ok(None) -> IONotFoundError` translation for reads.
4. New `core/data/` (or `core/dataio/registry.py`) — `DataRegistry` + `DataRecord`,
   modeled on `core/functions/registry.py` + `core/functions/models.py`.
5. New `service/handlers/data_register.py` — modeled on
   `service/handlers/function_register.py`. Wire up `DATA_REGISTER` op in
   `transport/wire.py` and `transport/router_server.py`.
6. `core/consensus/` — `DataRegistrySyncBridge`, `ClusterState.data`,
   `DirtyTracker.mark_data_dirty`, encode/decode helpers, modeled on
   `registry_sync.py`/`state_machine.py`.
7. New blob-streaming component — background loop + `DATA_BLOB_STREAM` op + follower
   chunk-buffering handler. Last, since it depends on 4-6 existing first.

Don't re-litigate the Key-abstraction, unification, or replication-strategy decisions
above without new information — they were deliberated over several turns.
