import pytest

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_endpoint.core.network import Command
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey
from axo_endpoint.service.handlers import FunctionRegisterHandler


@pytest.fixture
def registry():
    return FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=InMemoryEventBus())


def test_register_returns_function_id_and_version(registry):
    handler = FunctionRegisterHandler(registry=registry, now_fn=lambda: 100.0)
    command = Command(
        operation="FUNCTION_REGISTER",
        content_type="application/octet-stream",
        envelope={"name": "add", "version": 1},
        payload=b"code-bytes",
    )

    result = handler.handle(command)

    assert result.ok is True
    assert result.metadata == {"function_id": "add", "version": 1}

    record = registry.get(StorageKey(id="add", version=1, alias="add")).unwrap()
    assert record.code == b"code-bytes"


def test_missing_name_or_version_returns_error(registry):
    handler = FunctionRegisterHandler(registry=registry)
    result = handler.handle(
        Command(operation="FUNCTION_REGISTER", content_type="application/octet-stream", envelope={})
    )
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
    assert result.error_code == 1001
