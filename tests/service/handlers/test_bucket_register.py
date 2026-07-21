import pytest

from axo_endpoint.core.data import BucketRegistry
from axo_endpoint.core.events import InMemoryEventBus
from axo_shared.protocol import Command
from axo_endpoint.core.storage import InMemoryStorageBackend
from axo_endpoint.service.handlers import BucketRegisterHandler


@pytest.fixture
def registry():
    return BucketRegistry(catalog=InMemoryStorageBackend(), event_bus=InMemoryEventBus())


def test_register_returns_bucket_metadata(registry):
    handler = BucketRegisterHandler(registry=registry, now_fn=lambda: 100.0)
    result = handler.handle(Command(
        operation="BUCKET_REGISTER", content_type="application/json",
        envelope={"name": "mybucket", "quota_bytes": 1024},
    ))

    assert result.ok is True
    assert result.metadata == {"name": "mybucket", "quota_bytes": 1024, "created_at": 100.0}


def test_missing_required_field_returns_error(registry):
    handler = BucketRegisterHandler(registry=registry)
    result = handler.handle(
        Command(operation="BUCKET_REGISTER", content_type="application/json", envelope={"name": "mybucket"})
    )
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
    assert result.error_code == 1001


def test_duplicate_name_returns_bucket_already_exists(registry):
    handler = BucketRegisterHandler(registry=registry)
    handler.handle(Command(
        operation="BUCKET_REGISTER", content_type="application/json",
        envelope={"name": "mybucket", "quota_bytes": 1024},
    ))
    result = handler.handle(Command(
        operation="BUCKET_REGISTER", content_type="application/json",
        envelope={"name": "mybucket", "quota_bytes": 2048},
    ))
    assert result.ok is False
    assert result.error_name == "BUCKET_ALREADY_EXISTS"
    assert result.error_code == 7002
