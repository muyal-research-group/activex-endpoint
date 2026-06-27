import pytest
import zmq
from option import Ok

from axo_endpoint.core.events import Event, InMemoryEventBus
from axo_endpoint.core.network import Command, CommandResult
from axo_endpoint.core.results import FunctionResult
from axo_endpoint.core.runtime import FunctionRuntime, InvocationHandle
from axo_endpoint.core.storage import InMemoryStorageBackend, StorageKey
from axo_endpoint.dispatch import InMemoryCommandDispatcher
from axo_endpoint.service.handlers import JobResultHandler, JobSubmitHandler, PingHandler, build_completion_recorder
from axo_endpoint.service.transport import wire
from axo_endpoint.service.transport.router_server import RouterServer


def _bind_address(tmp_path, name="router"):
    return f"ipc://{tmp_path}/{name}.sock"


def _send_command(dealer, command: Command) -> CommandResult:
    dealer.send_multipart(wire.encode_command(command))
    frames = dealer.recv_multipart()
    return wire.decode_command_result(frames).unwrap()


@pytest.fixture
def dealer():
    socket = zmq.Context.instance().socket(zmq.DEALER)
    socket.setsockopt(zmq.RCVTIMEO, 500)
    yield socket
    socket.close()


class _ControllableRuntime(FunctionRuntime):
    """Accepts invocations without spawning anything real; the test drives
    completion explicitly via the same on_complete callback the dispatcher
    layer would have wired into a real ProcessFunctionRuntime."""

    def __init__(self):
        self.invocations = []

    def invoke(self, function_ref, job_id, params):
        self.invocations.append((function_ref, job_id, params))
        return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id))


def test_ping_round_trips_over_router_dealer(tmp_path, dealer):
    address = _bind_address(tmp_path)
    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=1)
    server = RouterServer(
        bind_address=address,
        direct_handlers={wire.PING: PingHandler()},
        dispatcher=dispatcher,
        results=InMemoryStorageBackend(),
        event_bus=InMemoryEventBus(),
    )
    server.start()
    dealer.connect(address)

    result = _send_command(dealer, Command(operation=wire.PING, content_type="application/json", envelope={}))
    assert result == CommandResult(ok=True)

    server.stop()
    dispatcher.close()


def test_malformed_request_is_dropped_without_crashing_server(tmp_path, dealer):
    address = _bind_address(tmp_path)
    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=1)
    server = RouterServer(
        bind_address=address,
        direct_handlers={wire.PING: PingHandler()},
        dispatcher=dispatcher,
        results=InMemoryStorageBackend(),
        event_bus=InMemoryEventBus(),
    )
    server.start()
    dealer.connect(address)

    dealer.send_multipart([b"too-few-frames"])  # decode_command will Err -- must be dropped, not crash

    result = _send_command(dealer, Command(operation=wire.PING, content_type="application/json", envelope={}))
    assert result == CommandResult(ok=True)

    server.stop()
    dispatcher.close()


def test_job_submit_returns_queued_then_pushes_completion_unsolicited(tmp_path, dealer):
    address = _bind_address(tmp_path)
    results_store = InMemoryStorageBackend()
    event_bus = InMemoryEventBus()
    on_complete = build_completion_recorder(results=results_store, event_bus=event_bus, now_fn=lambda: 100.0)

    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=2)
    dispatcher.register_handler(
        wire.JOB_SUBMIT,
        JobSubmitHandler(runtime=_ControllableRuntime(), results=results_store, event_bus=event_bus, job_id_fn=lambda: "job1"),
    )
    dispatcher.register_handler(wire.JOB_RESULT, JobResultHandler(results=results_store))

    server = RouterServer(
        bind_address=address,
        direct_handlers={},
        dispatcher=dispatcher,
        results=results_store,
        event_bus=event_bus,
    )
    server.start()
    dealer.connect(address)

    submit_result = _send_command(
        dealer,
        Command(
            operation=wire.JOB_SUBMIT,
            content_type="application/json",
            envelope={"function_name": "add", "function_version": 1, "params": {}},
        ),
    )
    assert submit_result.ok is True
    assert submit_result.metadata == {"job_id": "job1", "status": "QUEUED"}

    # Job finishes later -- nothing was sent on the dealer to ask for it.
    on_complete(InvocationHandle(job_id="job1", function_id="add"), Ok(5))

    pushed_frames = dealer.recv_multipart()
    pushed_result = wire.decode_command_result(pushed_frames).unwrap()
    assert pushed_result.ok is True
    assert pushed_result.metadata["pushed"] is True
    assert pushed_result.metadata["status"] == "COMPLETED"
    assert pushed_result.metadata["values"] == {"value": 5}

    server.stop()
    dispatcher.close()


def test_job_result_polling_still_works_when_push_target_is_unknown(tmp_path, dealer):
    address = _bind_address(tmp_path)
    results_store = InMemoryStorageBackend()
    event_bus = InMemoryEventBus()
    on_complete = build_completion_recorder(results=results_store, event_bus=event_bus, now_fn=lambda: 100.0)

    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=2)
    dispatcher.register_handler(
        wire.JOB_SUBMIT,
        JobSubmitHandler(runtime=_ControllableRuntime(), results=results_store, event_bus=event_bus, job_id_fn=lambda: "job1"),
    )
    dispatcher.register_handler(wire.JOB_RESULT, JobResultHandler(results=results_store))

    server = RouterServer(
        bind_address=address,
        direct_handlers={},
        dispatcher=dispatcher,
        results=results_store,
        event_bus=event_bus,
    )
    server.start()
    dealer.connect(address)

    submit_result = _send_command(
        dealer,
        Command(
            operation=wire.JOB_SUBMIT,
            content_type="application/json",
            envelope={"function_name": "add", "function_version": 1, "params": {}},
        ),
    )
    job_id = submit_result.metadata["job_id"]

    # Simulate a disconnect/identity change: the server no longer knows who to push to.
    with server._job_identities_lock:
        server._job_identities.pop(job_id, None)

    on_complete(InvocationHandle(job_id=job_id, function_id="add"), Ok(5))

    # No push arrives (popped above) -- the very next recv must be this poll's own reply,
    # not a stray push, which is exactly what's being proven here.
    result = _send_command(
        dealer, Command(operation=wire.JOB_RESULT, content_type="application/json", envelope={"job_id": job_id})
    )
    assert result.ok is True
    assert result.metadata["status"] == "COMPLETED"
    assert result.metadata["values"] == {"value": 5}

    server.stop()
    dispatcher.close()


def test_polling_a_completed_result_prevents_a_later_duplicate_push(tmp_path, dealer):
    address = _bind_address(tmp_path)
    results_store = InMemoryStorageBackend()
    event_bus = InMemoryEventBus()

    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=2)
    dispatcher.register_handler(
        wire.JOB_SUBMIT,
        JobSubmitHandler(runtime=_ControllableRuntime(), results=results_store, event_bus=event_bus, job_id_fn=lambda: "job1"),
    )
    dispatcher.register_handler(wire.JOB_RESULT, JobResultHandler(results=results_store))

    server = RouterServer(
        bind_address=address,
        direct_handlers={},
        dispatcher=dispatcher,
        results=results_store,
        event_bus=event_bus,
    )
    server.start()
    dealer.connect(address)

    submit_result = _send_command(
        dealer,
        Command(
            operation=wire.JOB_SUBMIT,
            content_type="application/json",
            envelope={"function_name": "add", "function_version": 1, "params": {}},
        ),
    )
    job_id = submit_result.metadata["job_id"]

    # The result becomes available directly (simulating the runtime finishing)
    # *before* the JOB_COMPLETED event is emitted/processed.
    results_store.put(StorageKey(id=job_id), FunctionResult(job_id=job_id, ok=True, values={"value": 5}))

    polled = _send_command(
        dealer, Command(operation=wire.JOB_RESULT, content_type="application/json", envelope={"job_id": job_id})
    )
    assert polled.metadata["status"] == "COMPLETED"
    assert job_id not in server._job_identities  # the client already fetched it itself

    # A late JOB_COMPLETED event must not trigger a push -- nobody to push to anymore.
    event_bus.emit(Event(event_type="JOB_COMPLETED", payload={"job_id": job_id, "function_id": "add"}, timestamp=200.0))

    with pytest.raises(zmq.Again):
        dealer.recv_multipart()

    server.stop()
    dispatcher.close()
