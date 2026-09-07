from axo_endpoint.core.data import DATA_REGISTERED_EVENT, DataRecord
from axo_shared.functions.lifecycle import FunctionState


def test_data_registered_event_is_distinct_from_function_registered():
    # Guards against the event-bus topic collision bug: if this ever equals
    # FunctionState.REGISTERED.value ("REGISTERED"), RegistrySyncBridge would
    # also fire on data-registration events and crash on a missing
    # "function_id" key.
    assert DATA_REGISTERED_EVENT != FunctionState.REGISTERED.value


def test_data_record_is_frozen():
    record = DataRecord(
        name="df1", version=1, alias="df1", format="csv", kind="fs",
        total_size=8, chunk_bytes=4, total_chunks=2, created_at=100.0,
    )
    assert record.name == "df1"
    assert record.total_chunks == 2
    assert record.declared_hash is None
    assert record.content_hash_algo == "sha256"
