import pytest

from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.core.functions import FunctionRegistry
from axo_shared.protocol import Command
from axo_shared.runtime.spec import RuntimeSpec
from axo_endpoint.core.storage import InMemoryStorageBackend
from axo_endpoint.service.handlers.container_bootstrap import ContainerBootstrapHandler


@pytest.fixture
def registry():
    return FunctionRegistry(backend=InMemoryStorageBackend(), event_bus=InMemoryEventBus())


def test_bootstrap_returns_code_requirements_and_code_format(registry):
    registry.register(
        function_id="add", name="add", code=b"def add(params, ctx): ...", now=100.0,
        runtime_spec=RuntimeSpec(requirements=["pandas"]), code_format="source",
    )
    handler = ContainerBootstrapHandler(registry=registry)

    result = handler.handle(Command(
        operation="CONTAINER_BOOTSTRAP", content_type="application/json",
        envelope={"function_id": "add", "version": 1}, payload=b"",
    ))

    assert result.ok is True
    assert result.payload == b"def add(params, ctx): ..."
    assert result.metadata == {"requirements": ["pandas"], "code_format": "source", "name": "add"}


def test_bootstrap_returns_the_record_name_not_the_function_id(registry):
    """function_id is a content-derived hash, distinct from the caller-given
    display name -- a container materializing "source"-format code needs the
    latter to find the top-level def, so this metadata field must carry the
    real name even when it differs from the id."""
    registry.register(
        function_id="377022c9ad309107a47495eb5599f711f8881837a888180f9b039a690ecb1bde",
        name="fy", code=b"def fy(params, ctx): ...", now=100.0, code_format="source",
    )
    handler = ContainerBootstrapHandler(registry=registry)

    result = handler.handle(Command(
        operation="CONTAINER_BOOTSTRAP", content_type="application/json",
        envelope={"function_id": "377022c9ad309107a47495eb5599f711f8881837a888180f9b039a690ecb1bde", "version": 1},
        payload=b"",
    ))

    assert result.metadata["name"] == "fy"


def test_bootstrap_defaults_code_format_to_cloudpickle(registry):
    registry.register(function_id="add", name="add", code=b"pickled-bytes", now=100.0)
    handler = ContainerBootstrapHandler(registry=registry)

    result = handler.handle(Command(
        operation="CONTAINER_BOOTSTRAP", content_type="application/json",
        envelope={"function_id": "add", "version": 1}, payload=b"",
    ))

    assert result.metadata["code_format"] == "cloudpickle"


def test_bootstrap_returns_error_for_unregistered_function(registry):
    handler = ContainerBootstrapHandler(registry=registry)

    result = handler.handle(Command(
        operation="CONTAINER_BOOTSTRAP", content_type="application/json",
        envelope={"function_id": "missing", "version": 1}, payload=b"",
    ))

    assert result.ok is False


def test_bootstrap_returns_error_for_missing_fields(registry):
    handler = ContainerBootstrapHandler(registry=registry)

    result = handler.handle(Command(
        operation="CONTAINER_BOOTSTRAP", content_type="application/json", envelope={}, payload=b"",
    ))

    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"
