import dataclasses

import pytest

from axo_endpoint.core.events import Event, EventBus


def test_event_equality_and_defaults():
    a = Event(event_type="JOB_COMPLETED", payload={"job_id": "j1"})
    b = Event(event_type="JOB_COMPLETED", payload={"job_id": "j1"})
    assert a == b
    assert a.timestamp == 0.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.timestamp = 1.0


def test_event_default_payload_is_not_shared_between_instances():
    a = Event(event_type="A")
    b = Event(event_type="B")
    a.payload["x"] = 1
    assert b.payload == {}


def test_event_bus_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        EventBus()


class _DictEventBus(EventBus):
    """Trivial in-memory implementation used only to exercise the contract."""

    def __init__(self):
        self._subscribers = {}

    def emit(self, event: Event) -> None:
        for handler in self._subscribers.get(event.event_type, []):
            handler(event)

    def subscribe(self, event_type, handler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)


def test_subscribe_then_emit_calls_handler_with_event():
    bus = _DictEventBus()
    received = []
    bus.subscribe("JOB_COMPLETED", received.append)

    event = Event(event_type="JOB_COMPLETED", payload={"job_id": "j1"})
    bus.emit(event)

    assert received == [event]


def test_emit_with_no_subscribers_is_a_noop():
    bus = _DictEventBus()
    bus.emit(Event(event_type="JOB_COMPLETED"))  # must not raise


def test_emit_only_calls_handlers_subscribed_to_that_event_type():
    bus = _DictEventBus()
    completed = []
    failed = []
    bus.subscribe("JOB_COMPLETED", completed.append)
    bus.subscribe("JOB_FAILED", failed.append)

    bus.emit(Event(event_type="JOB_COMPLETED"))

    assert len(completed) == 1
    assert len(failed) == 0
