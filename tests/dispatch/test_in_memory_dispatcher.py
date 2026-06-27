import threading
import time

from axo_endpoint.core.network import Command, CommandHandler, CommandResult
from axo_endpoint.dispatch import InMemoryCommandDispatcher


def _wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _EchoHandler(CommandHandler):
    def handle(self, command: Command) -> CommandResult:
        return CommandResult(ok=True, payload=command.payload)


def test_register_handler_then_submit_routes_to_it_and_returns_its_result():
    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=1)
    dispatcher.register_handler("ECHO", _EchoHandler())

    result = dispatcher.submit(Command(operation="ECHO", content_type="x", envelope={}, payload=b"hi"))
    dispatcher.close()

    assert result == CommandResult(ok=True, payload=b"hi")


def test_unregistered_operation_returns_unknown_operation():
    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=1)

    result = dispatcher.submit(Command(operation="NOPE", content_type="x", envelope={}))
    dispatcher.close()

    assert result.ok is False
    assert result.error_name == "UNKNOWN_OPERATION"
    assert result.error_code == 1003


def test_handler_exception_is_translated_to_failed_command_result():
    class BoomHandler(CommandHandler):
        def handle(self, command: Command) -> CommandResult:
            raise ValueError("boom")

    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=1)
    dispatcher.register_handler("BOOM", BoomHandler())

    result = dispatcher.submit(Command(operation="BOOM", content_type="x", envelope={}))
    dispatcher.close()

    assert result.ok is False
    assert "boom" in result.error


def test_concurrent_submits_are_dispatched_to_separate_worker_threads():
    started = []
    started_lock = threading.Lock()
    release = threading.Event()

    class SlowHandler(CommandHandler):
        def handle(self, command: Command) -> CommandResult:
            with started_lock:
                started.append(command.envelope["n"])
            release.wait(timeout=2)
            return CommandResult(ok=True)

    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=2)
    dispatcher.register_handler("SLOW", SlowHandler())

    results = []

    def call(n):
        results.append(dispatcher.submit(Command(operation="SLOW", content_type="x", envelope={"n": n})))

    t1 = threading.Thread(target=call, args=(1,))
    t2 = threading.Thread(target=call, args=(2,))
    t1.start()
    t2.start()

    # Both workers must have picked up their command before either is allowed
    # to finish — proves genuinely concurrent dispatch, not serialized.
    assert _wait_until(lambda: len(started) == 2)

    release.set()
    t1.join(timeout=2)
    t2.join(timeout=2)
    dispatcher.close()

    assert len(results) == 2
    assert all(r.ok for r in results)


def test_full_queue_returns_queue_full_without_blocking():
    block = threading.Event()

    class BlockingHandler(CommandHandler):
        def handle(self, command: Command) -> CommandResult:
            block.wait(timeout=2)
            return CommandResult(ok=True)

    dispatcher = InMemoryCommandDispatcher(max_queue_size=1, worker_count=1)
    dispatcher.register_handler("BLOCK", BlockingHandler())

    t1 = threading.Thread(
        target=dispatcher.submit, args=(Command(operation="BLOCK", content_type="x", envelope={}),)
    )
    t1.start()
    # Wait for the single worker to dequeue and start executing item 1,
    # which empties the queue and leaves room for exactly one more item.
    assert _wait_until(lambda: dispatcher.metrics()["submitted"] >= 1)

    t2 = threading.Thread(
        target=dispatcher.submit, args=(Command(operation="BLOCK", content_type="x", envelope={}),)
    )
    t2.start()
    assert _wait_until(lambda: dispatcher.metrics()["queue_depth"] == 1)

    result = dispatcher.submit(Command(operation="BLOCK", content_type="x", envelope={}))
    assert result.ok is False
    assert result.error_name == "QUEUE_FULL"
    assert result.error_code == 4001

    block.set()
    t1.join(timeout=2)
    t2.join(timeout=2)
    dispatcher.close()


def test_close_lets_in_flight_handler_finish_then_rejects_further_submits():
    started = threading.Event()
    finish = threading.Event()

    class SlowHandler(CommandHandler):
        def handle(self, command: Command) -> CommandResult:
            started.set()
            finish.wait(timeout=2)
            return CommandResult(ok=True)

    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=1)
    dispatcher.register_handler("SLOW", SlowHandler())

    result_holder = {}

    def call():
        result_holder["result"] = dispatcher.submit(Command(operation="SLOW", content_type="x", envelope={}))

    t = threading.Thread(target=call)
    t.start()
    assert started.wait(timeout=2)

    close_thread = threading.Thread(target=dispatcher.close)
    close_thread.start()

    finish.set()
    t.join(timeout=2)
    close_thread.join(timeout=2)

    assert result_holder["result"] == CommandResult(ok=True)

    rejected = dispatcher.submit(Command(operation="SLOW", content_type="x", envelope={}))
    assert rejected.ok is False
    assert rejected.error_name == "DISPATCHER_CLOSED"
    assert rejected.error_code == 4002


def test_metrics_tracks_submitted_completed_and_failed_counts():
    class OkHandler(CommandHandler):
        def handle(self, command: Command) -> CommandResult:
            return CommandResult(ok=True)

    class FailHandler(CommandHandler):
        def handle(self, command: Command) -> CommandResult:
            return CommandResult(ok=False, error="nope")

    dispatcher = InMemoryCommandDispatcher(max_queue_size=10, worker_count=2)
    dispatcher.register_handler("OK", OkHandler())
    dispatcher.register_handler("FAIL", FailHandler())

    dispatcher.submit(Command(operation="OK", content_type="x", envelope={}))
    dispatcher.submit(Command(operation="OK", content_type="x", envelope={}))
    dispatcher.submit(Command(operation="FAIL", content_type="x", envelope={}))
    dispatcher.close()

    metrics = dispatcher.metrics()
    assert metrics["submitted"] == 3
    assert metrics["completed"] == 2
    assert metrics["failed"] == 1
