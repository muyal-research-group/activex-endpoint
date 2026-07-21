import pytest

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.protocol import Command
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey
from axo_endpoint.service.handlers import FunctionRegisterHandler


@pytest.fixture
def registry():
    return FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=InMemoryEventBus())


def test_register_returns_function_id_and_backend_assigned_version(registry):
    handler = FunctionRegisterHandler(registry=registry, now_fn=lambda: 100.0)
    command = Command(
        operation="FUNCTION_REGISTER",
        content_type="application/octet-stream",
        envelope={"function_id": "add", "name": "add"},
        payload=b"code-bytes",
    )

    result = handler.handle(command)

    assert result.ok is True
    assert result.metadata == {"function_id": "add", "version": 1}

    record = registry.get(StorageKey(id="add", version=1, alias="add")).unwrap()
    assert record.function_id == "add"
    assert record.code == b"code-bytes"
    assert record.code_format == "cloudpickle"


def test_register_again_under_same_function_id_bumps_version(registry):
    handler = FunctionRegisterHandler(registry=registry, now_fn=lambda: 100.0)
    envelope = {"function_id": "add", "name": "add"}

    first = handler.handle(
        Command(operation="FUNCTION_REGISTER", content_type="application/octet-stream", envelope=envelope, payload=b"v1")
    )
    second = handler.handle(
        Command(operation="FUNCTION_REGISTER", content_type="application/octet-stream", envelope=envelope, payload=b"v2")
    )

    assert first.metadata["version"] == 1
    assert second.metadata["version"] == 2


def test_register_stores_source_code_format_when_provided(registry):
    handler = FunctionRegisterHandler(registry=registry, now_fn=lambda: 100.0)
    command = Command(
        operation="FUNCTION_REGISTER",
        content_type="application/octet-stream",
        envelope={"function_id": "add", "name": "add", "code_format": "source"},
        payload=b"def add(params, ctx): ...",
    )

    handler.handle(command)

    record = registry.get(StorageKey(id="add", version=1, alias="add")).unwrap()
    assert record.code_format == "source"


def test_missing_function_id_or_name_returns_error(registry):
    handler = FunctionRegisterHandler(registry=registry)
    result = handler.handle(
        Command(operation="FUNCTION_REGISTER", content_type="application/octet-stream", envelope={})
    )
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
    assert result.error_code == 1001
