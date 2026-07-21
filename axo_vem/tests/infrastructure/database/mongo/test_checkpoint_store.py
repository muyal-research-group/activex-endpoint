import mongomock

from axo_vem.infrastructure.database.mongo.checkpoint_store import MongoCheckpointStore


def _store():
    collection = mongomock.MongoClient()["test"]["projector_checkpoints"]
    return MongoCheckpointStore(collection)


def test_get_position_returns_none_when_no_checkpoint_yet():
    store = _store()
    assert store.get_position() is None


def test_set_then_get_round_trips():
    store = _store()
    store.set_position(42)
    assert store.get_position() == 42


def test_set_position_is_idempotent_upsert():
    store = _store()
    store.set_position(1)
    store.set_position(2)
    store.set_position(3)
    assert store.get_position() == 3
