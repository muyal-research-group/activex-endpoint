import time

import zmq

from axo_shared.events import envelope, models
from axo_shared import wire

from axo_endpoint.service.transport.event_publisher import ZmqEventPublisher


def test_publish_round_trips_through_loopback_router():
    ctx = zmq.Context.instance()
    router = ctx.socket(zmq.ROUTER)
    router.bind("tcp://127.0.0.1:0")
    address = router.getsockopt(zmq.LAST_ENDPOINT).decode("utf-8")
    router.setsockopt(zmq.RCVTIMEO, 2000)

    publisher = ZmqEventPublisher(api_uri=address, endpoint_id="n0", context=ctx)
    try:
        event = models.EndpointStarted(
            endpoint_id="n0", router_bind="tcp://0.0.0.0:5555", pub_bind="tcp://0.0.0.0:5556",
        )
        publisher.publish(models.ENDPOINT_STARTED, event.model_dump(mode="json"))

        frames = router.recv_multipart()
        # ROUTER prepends the sender's identity as frame 0.
        command_result = wire.decode_command(frames[1:])
        assert command_result.is_ok
        command = command_result.unwrap()
        assert command.operation == wire.EVENT_PUBLISH

        event_result = envelope.decode_event(command)
        assert event_result.is_ok
        event_type, endpoint_id, data = event_result.unwrap()
        assert event_type == models.ENDPOINT_STARTED
        assert endpoint_id == "n0"
        assert data["router_bind"] == "tcp://0.0.0.0:5555"
    finally:
        publisher.close()
        router.close()


def test_publish_immediately_followed_by_close_still_delivers():
    """Regression test for App.stop()'s shutdown sequence: publish()
    EndpointStopped then close() the socket right after, with no
    intervening work to let ZMQ's I/O thread flush on its own."""
    ctx = zmq.Context.instance()
    router = ctx.socket(zmq.ROUTER)
    router.bind("tcp://127.0.0.1:0")
    address = router.getsockopt(zmq.LAST_ENDPOINT).decode("utf-8")
    router.setsockopt(zmq.RCVTIMEO, 2000)

    publisher = ZmqEventPublisher(api_uri=address, endpoint_id="n0", context=ctx)
    event = models.EndpointStopped(endpoint_id="n0", uptime_ms=42.0)
    publisher.publish(models.ENDPOINT_STOPPED, event.model_dump(mode="json"))
    publisher.close()

    try:
        frames = router.recv_multipart()
        command = wire.decode_command(frames[1:]).unwrap()
        event_type, endpoint_id, data = envelope.decode_event(command).unwrap()
        assert event_type == models.ENDPOINT_STOPPED
        assert endpoint_id == "n0"
        assert data["uptime_ms"] == 42.0
    finally:
        router.close()


def test_publish_never_blocks_when_nothing_is_listening():
    ctx = zmq.Context.instance()
    # No socket bound at this address -- publish() must still return promptly.
    publisher = ZmqEventPublisher(api_uri="tcp://127.0.0.1:59991", endpoint_id="n0", context=ctx)
    try:
        started = time.monotonic()
        for _ in range(5):
            event = models.EndpointMetricsReported(endpoint_id="n0", metrics={})
            publisher.publish(models.ENDPOINT_METRICS_REPORTED, event.model_dump(mode="json"))
        elapsed = time.monotonic() - started
        assert elapsed < 1.0
    finally:
        publisher.close()
