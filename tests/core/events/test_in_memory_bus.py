from axo_endpoint.core.events import Event, InMemoryEventBus


def test_emit_with_no_subscribers_is_a_noop():
    bus = InMemoryEventBus()
    bus.emit(Event(event_type="JOB_COMPLETED"))  # must not raise


def test_subscribe_then_emit_calls_handler_with_event():
    bus = InMemoryEventBus()
    received = []
    bus.subscribe("JOB_COMPLETED", received.append)

    event = Event(event_type="JOB_COMPLETED", payload={"job_id": "j1"})
    bus.emit(event)

    assert received == [event]


def test_multiple_subscribers_to_same_event_type_all_called():
    bus = InMemoryEventBus()
    first, second = [], []
    bus.subscribe("JOB_COMPLETED", first.append)
    bus.subscribe("JOB_COMPLETED", second.append)

    event = Event(event_type="JOB_COMPLETED")
    bus.emit(event)

    assert first == [event]
    assert second == [event]


def test_raising_subscriber_does_not_prevent_other_subscribers_from_running():
    bus = InMemoryEventBus()
    survived = []

    def boom(_event):
        raise ValueError("boom")

    bus.subscribe("JOB_COMPLETED", boom)
    bus.subscribe("JOB_COMPLETED", survived.append)

    bus.emit(Event(event_type="JOB_COMPLETED"))  # must not raise

    assert len(survived) == 1


def test_handler_error_callback_receives_event_type_and_exception():
    bus_errors = []
    bus = InMemoryEventBus(on_handler_error=lambda event_type, exc: bus_errors.append((event_type, exc)))

    def boom(_event):
        raise ValueError("boom")

    bus.subscribe("JOB_FAILED", boom)
    bus.emit(Event(event_type="JOB_FAILED"))

    assert len(bus_errors) == 1
    event_type, exc = bus_errors[0]
    assert event_type == "JOB_FAILED"
    assert isinstance(exc, ValueError)


def test_no_error_callback_silently_swallows_handler_exception():
    bus = InMemoryEventBus()

    def boom(_event):
        raise ValueError("boom")

    bus.subscribe("JOB_FAILED", boom)
    bus.emit(Event(event_type="JOB_FAILED"))  # must not raise, no callback configured
