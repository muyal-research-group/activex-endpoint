from axo_shared.protocol import Command
from axo_endpoint.core.consensus.concurrency import ConcurrencyLedger
from axo_endpoint.core.events import InMemoryEventBus
from axo_endpoint.service.container.handle import ContainerHandle, ContainerStatus
from axo_endpoint.service.container.spawner import ContainerSummoner
from axo_endpoint.service.handlers.concurrency_reconcile_pull import ConcurrencyReconcilePullHandler
from axo_endpoint.service.handlers.concurrency_slot_release import ConcurrencySlotReleaseHandler
from axo_endpoint.service.handlers.concurrency_slot_request import ConcurrencySlotRequestHandler


class _FakeConfig:
    AXO_ENDPOINT_ID = "axo-endpoint-test"
    AXO_ENDPOINT_CONTAINER_JOB_PORT = 5600
    AXO_ENDPOINT_CONTAINER_FASTAPI_PORT = 8000
    AXO_ENDPOINT_CONTAINER_BACKEND = "docker"
    AXO_ENDPOINT_ROUTER_BIND = "tcp://0.0.0.0:5555"
    AXO_ENDPOINT_CONTAINER_RESULT_BIND = "tcp://0.0.0.0:5557"
    AXO_ENDPOINT_DATAIO_TIMEOUT_SECONDS = 30.0
    AXO_ENDPOINT_CONTAINER_NETWORK = "axo-net"
    AXO_ENDPOINT_CONTAINER_PIP_CACHE_VOLUME = "axo-pip-cache"
    AXO_ENDPOINT_CONTAINER_RUNNER_IMAGE = "axo-runner"
    AXO_ENDPOINT_CONTAINER_AUTO_BUILD_IMAGE = True
    AXO_ENDPOINT_CONTAINER_READINESS_TIMEOUT_SECONDS = 0.3
    AXO_ENDPOINT_CONTAINER_MEMORY_LIMIT_BYTES = 1073741824
    AXO_ENDPOINT_CONTAINER_CPU_LIMIT = 1.0


def test_slot_request_handler_returns_granted():
    handler = ConcurrencySlotRequestHandler(ledger=ConcurrencyLedger())

    result = handler.handle(Command(
        operation="CONCURRENCY_SLOT_REQUEST", content_type="application/json",
        envelope={"function_id": "fn1", "version": 1, "max_concurrency": 1, "requester_id": "A"},
    ))

    assert result.ok is True
    assert result.metadata == {"action": "granted", "slot_index": 0}


def test_slot_request_handler_returns_place_at_capacity():
    ledger = ConcurrencyLedger()
    ledger.request_slot("fn1", 1, 1, "A")
    handler = ConcurrencySlotRequestHandler(ledger=ledger)

    result = handler.handle(Command(
        operation="CONCURRENCY_SLOT_REQUEST", content_type="application/json",
        envelope={"function_id": "fn1", "version": 1, "max_concurrency": 1, "requester_id": "B"},
    ))

    assert result.ok is True
    assert result.metadata == {"action": "place", "target_endpoint_id": "A"}


def test_slot_request_handler_surfaces_retry_as_an_error():
    ledger = ConcurrencyLedger()
    ledger.begin_reconciliation()
    handler = ConcurrencySlotRequestHandler(ledger=ledger)

    result = handler.handle(Command(
        operation="CONCURRENCY_SLOT_REQUEST", content_type="application/json",
        envelope={"function_id": "fn1", "version": 1, "max_concurrency": 1, "requester_id": "A"},
    ))

    assert result.ok is False
    assert result.error_name == "CONCURRENCY_LEDGER_NOT_READY"


def test_slot_request_handler_missing_fields():
    handler = ConcurrencySlotRequestHandler(ledger=ConcurrencyLedger())

    result = handler.handle(Command(operation="CONCURRENCY_SLOT_REQUEST", content_type="application/json", envelope={}))

    assert result.ok is False
    assert result.error_name == "MISSING_FIELD"


def test_slot_release_handler_frees_the_slot_for_reuse():
    ledger = ConcurrencyLedger()
    ledger.request_slot("fn1", 1, 1, "A")
    handler = ConcurrencySlotReleaseHandler(ledger=ledger)

    result = handler.handle(Command(
        operation="CONCURRENCY_SLOT_RELEASE", content_type="application/json",
        envelope={"function_id": "fn1", "version": 1, "slot_index": 0, "endpoint_id": "A"},
    ))

    assert result.ok is True
    decision = ledger.request_slot("fn1", 1, 1, "B")
    assert decision.action == "granted"
    assert decision.slot_index == 0


def test_reconcile_pull_handler_reports_live_containers_only():
    event_bus = InMemoryEventBus()
    summoner = ContainerSummoner(config=_FakeConfig(), event_bus=event_bus)
    live = ContainerHandle(
        function_id="fn1", version=1, service_name="fn-fn1-v1", mode="docker",
        zmq_address="tcp://x:5600", http_address="http://x:8000", pool_index=0,
    )
    live.status = ContainerStatus.IDLE
    crashed = ContainerHandle(
        function_id="fn1", version=1, service_name="fn-fn1-v1-p1", mode="docker",
        zmq_address="tcp://x:5600", http_address="http://x:8000", pool_index=1,
    )
    crashed.status = ContainerStatus.CRASHED
    with summoner._lock:
        summoner._handles[("fn1", 1)] = [live, crashed]
    handler = ConcurrencyReconcilePullHandler(summoner=summoner)

    result = handler.handle(Command(operation="CONCURRENCY_RECONCILE_PULL", content_type="application/json", envelope={}))

    assert result.ok is True
    assert result.metadata == {"entries": [{"function_id": "fn1", "version": 1, "slot_index": 0}]}
