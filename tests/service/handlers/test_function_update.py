import pytest

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.protocol import Command
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey
from axo_endpoint.service.handlers import FunctionUpdateHandler


@pytest.fixture
def registry():
    return FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=InMemoryEventBus())


def test_update_merges_env_vars_and_params_schema(registry):
    registry.register(function_id="add", name="add", code=b"code", now=100.0)
    handler = FunctionUpdateHandler(registry=registry, now_fn=lambda: 200.0)

    result = handler.handle(Command(
        operation="FUNCTION_UPDATE",
        content_type="application/json",
        envelope={
            "function_id": "add", "version": 1,
            "env_vars": {"A": "1"},
            "params_schema": [{"name": "x", "type": "number", "required": False}],
        },
    ))

    assert result.ok is True
    assert result.metadata == {"function_id": "add", "version": 1}

    record = registry.get(StorageKey(id="add", version=1, alias="add")).unwrap()
    assert record.runtime_spec.env_vars == {"A": "1"}
    assert [p.name for p in record.params_schema] == ["x"]


def test_missing_function_id_or_version_returns_error(registry):
    handler = FunctionUpdateHandler(registry=registry)
    result = handler.handle(
        Command(operation="FUNCTION_UPDATE", content_type="application/json", envelope={})
    )
    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
    assert result.error_code == 1001


def test_update_on_unregistered_function_returns_error(registry):
    handler = FunctionUpdateHandler(registry=registry)
    result = handler.handle(Command(
        operation="FUNCTION_UPDATE", content_type="application/json",
        envelope={"function_id": "missing", "version": 1, "env_vars": {"A": "1"}},
    ))
    assert result.ok is False
    assert result.error_name == "STORAGE_ERROR"
