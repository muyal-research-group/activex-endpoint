import pytest

from axo_endpoint.core.data.bucket_models import BUCKET_REGISTERED_EVENT, DataBucket
from axo_endpoint.core.data.bucket_registry import BucketRegistry
from axo_endpoint.core.errors import BucketAlreadyExistsError
from axo_endpoint.core.events import Event, InMemoryEventBus
from axo_endpoint.core.storage import InMemoryStorageBackend


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def registry(event_bus):
    return BucketRegistry(catalog=InMemoryStorageBackend(), event_bus=event_bus)


def test_register_stores_bucket_and_emits_event(registry, event_bus):
    received = []
    event_bus.subscribe(BUCKET_REGISTERED_EVENT, received.append)

    result = registry.register(name="mybucket", quota_bytes=1024, now=100.0)

    assert result.is_ok
    bucket = result.unwrap()
    assert bucket == DataBucket(name="mybucket", quota_bytes=1024, created_at=100.0)
    assert received == [
        Event(
            event_type=BUCKET_REGISTERED_EVENT,
            payload={"name": "mybucket", "quota_bytes": 1024, "created_at": 100.0},
            timestamp=100.0,
        )
    ]


def test_register_duplicate_name_is_rejected(registry):
    registry.register(name="mybucket", quota_bytes=1024, now=100.0)
    result = registry.register(name="mybucket", quota_bytes=2048, now=101.0)

    assert result.is_err
    assert isinstance(result.unwrap_err(), BucketAlreadyExistsError)


def test_get_returns_none_for_unknown_bucket(registry):
    result = registry.get("missing")
    assert result.is_ok
    assert result.unwrap() is None


def test_list_buckets_returns_every_registered_bucket(registry):
    registry.register(name="a", quota_bytes=1, now=0.0)
    registry.register(name="b", quota_bytes=2, now=0.0)

    names = {b.name for b in registry.list_buckets()}
    assert names == {"a", "b"}
