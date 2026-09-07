import hashlib

from option import Ok

from axo_shared.protocol import Command, CommandResult
from axo_endpoint.core.consensus.result_consistency import ResultConsistencyStore
from axo_endpoint.core.results import FunctionResult, encode_function_result
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey
from axo_endpoint.service.handlers.job_result_sync import JobResultReplicateHandler, JobResultSyncHandler


def _payload_and_hash(result: FunctionResult):
    payload = encode_function_result(result)
    return payload, hashlib.sha256(payload).hexdigest()


def test_sync_handler_stores_its_own_copy_and_fans_out_to_every_peer():
    results = InMemoryStorageBackend()
    store = ResultConsistencyStore()
    fanned_out = []

    def forward_fn(rpc_uri, command, timeout):
        fanned_out.append(rpc_uri)
        return Ok(CommandResult(ok=True))

    handler = JobResultSyncHandler(
        results=results,
        consistency_store=store,
        peer_rpc_uris_fn=lambda: ["tcp://peerB", "tcp://peerC"],
        forward_fn=forward_fn,
        max_retries=1,
        backoff_base_seconds=0.01,
        forward_timeout_seconds=1.0,
    )
    result = FunctionResult(job_id="job1", ok=True, output={"value": 42, "type": "json"})
    payload, result_hash = _payload_and_hash(result)

    outcome = handler.handle(Command(
        operation="JOB_RESULT_SYNC", content_type="application/octet-stream",
        envelope={"job_id": "job1", "hash": result_hash}, payload=payload,
    ))

    assert outcome.ok is True
    stored = results.get(StorageKey(id="job1")).unwrap()
    assert stored.output == {"value": 42, "type": "json"}
    assert store.get_state("job1") == "synced"
    assert sorted(fanned_out) == ["tcp://peerB", "tcp://peerC"]


def test_sync_handler_rejects_hash_mismatch_and_stores_nothing():
    results = InMemoryStorageBackend()
    store = ResultConsistencyStore()
    handler = JobResultSyncHandler(
        results=results, consistency_store=store, peer_rpc_uris_fn=lambda: [],
        forward_fn=lambda *a: Ok(CommandResult(ok=True)),
        max_retries=1, backoff_base_seconds=0.01, forward_timeout_seconds=1.0,
    )

    outcome = handler.handle(Command(
        operation="JOB_RESULT_SYNC", content_type="application/octet-stream",
        envelope={"job_id": "job1", "hash": "deadbeef"}, payload=b"garbage",
    ))

    assert outcome.ok is False
    assert outcome.error_name == "RESULT_HASH_MISMATCH"
    assert results.get(StorageKey(id="job1")).unwrap() is None


def test_sync_handler_missing_fields_returns_error():
    handler = JobResultSyncHandler(
        results=InMemoryStorageBackend(), consistency_store=ResultConsistencyStore(),
        peer_rpc_uris_fn=lambda: [], forward_fn=lambda *a: Ok(CommandResult(ok=True)),
        max_retries=1, backoff_base_seconds=0.01, forward_timeout_seconds=1.0,
    )

    outcome = handler.handle(Command(operation="JOB_RESULT_SYNC", content_type="application/json", envelope={}))

    assert outcome.ok is False
    assert outcome.error_name == "MISSING_FIELD"


def test_replicate_handler_stores_a_verified_copy():
    results = InMemoryStorageBackend()
    store = ResultConsistencyStore()
    handler = JobResultReplicateHandler(results=results, consistency_store=store)
    result = FunctionResult(job_id="job1", ok=False, error="boom")
    payload, result_hash = _payload_and_hash(result)

    outcome = handler.handle(Command(
        operation="JOB_RESULT_REPLICATE", content_type="application/octet-stream",
        envelope={"job_id": "job1", "hash": result_hash}, payload=payload,
    ))

    assert outcome.ok is True
    stored = results.get(StorageKey(id="job1")).unwrap()
    assert stored.ok is False
    assert stored.error == "boom"
    assert store.get_state("job1") == "synced"


def test_replicate_handler_discards_a_hash_mismatch_and_marks_inconsistent():
    results = InMemoryStorageBackend()
    store = ResultConsistencyStore()
    handler = JobResultReplicateHandler(results=results, consistency_store=store)

    outcome = handler.handle(Command(
        operation="JOB_RESULT_REPLICATE", content_type="application/octet-stream",
        envelope={"job_id": "job1", "hash": "deadbeef"}, payload=b"garbage",
    ))

    assert outcome.ok is False
    assert outcome.error_name == "RESULT_HASH_MISMATCH"
    assert results.get(StorageKey(id="job1")).unwrap() is None
    assert store.get_state("job1") == "inconsistent"
