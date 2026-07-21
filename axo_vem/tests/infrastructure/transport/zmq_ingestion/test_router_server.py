import zmq

from axo_shared import wire
from axo_shared.events import envelope, models

from axo_vem.infrastructure.transport.zmq_ingestion.router_server import IngestionRouterServer


class _FakeAppender:
    def __init__(self):
        self.appended = []

    def append_to_stream(self, stream_name, event_type, data):
        self.appended.append((stream_name, event_type, data))


def _send_event(dealer, event_type, endpoint_id, data):
    command = envelope.encode_event(event_type, endpoint_id, data)
    dealer.send_multipart(wire.encode_command(command))


def test_router_appends_decoded_event_to_the_right_stream():
    ctx = zmq.Context.instance()
    appender = _FakeAppender()
    server = IngestionRouterServer(bind_address="tcp://127.0.0.1:0", appender=appender, context=ctx)
    server.start()

    dealer = ctx.socket(zmq.DEALER)
    dealer.setsockopt(zmq.RCVTIMEO, 2000)
    dealer.connect(server.bind_address)

    try:
        event = models.EndpointStarted(
            endpoint_id="n0", router_bind="tcp://0.0.0.0:5555", pub_bind="tcp://0.0.0.0:5556",
        )
        _send_event(dealer, models.ENDPOINT_STARTED, "n0", event.model_dump(mode="json"))

        # Confirm the best-effort ack arrives too.
        frames = dealer.recv_multipart()
        result = wire.decode_command_result(frames).unwrap()
        assert result.ok is True

        assert len(appender.appended) == 1
        stream_name, event_type, data = appender.appended[0]
        assert stream_name == "endpoints-n0"
        assert event_type == models.ENDPOINT_STARTED
        assert data["router_bind"] == "tcp://0.0.0.0:5555"
    finally:
        dealer.close()
        server.stop()


def test_router_ignores_malformed_frames_without_crashing():
    ctx = zmq.Context.instance()
    appender = _FakeAppender()
    server = IngestionRouterServer(bind_address="tcp://127.0.0.1:0", appender=appender, context=ctx)
    server.start()

    dealer = ctx.socket(zmq.DEALER)
    dealer.setsockopt(zmq.RCVTIMEO, 300)
    dealer.connect(server.bind_address)

    try:
        dealer.send_multipart([b"not", b"a", b"valid", b"command", b"envelope"])

        # Send a real, valid event afterwards to confirm the server is still alive.
        event = models.EndpointMetricsReported(endpoint_id="n0", metrics={})
        _send_event(dealer, models.ENDPOINT_METRICS_REPORTED, "n0", event.model_dump(mode="json"))
        frames = dealer.recv_multipart()
        result = wire.decode_command_result(frames).unwrap()
        assert result.ok is True
        assert len(appender.appended) == 1
    finally:
        dealer.close()
        server.stop()


def test_router_appends_function_registered_to_functions_stream():
    ctx = zmq.Context.instance()
    appender = _FakeAppender()
    server = IngestionRouterServer(bind_address="tcp://127.0.0.1:0", appender=appender, context=ctx)
    server.start()

    dealer = ctx.socket(zmq.DEALER)
    dealer.setsockopt(zmq.RCVTIMEO, 2000)
    dealer.connect(server.bind_address)

    try:
        event = models.FunctionRegistered(endpoint_id="n0", function_id="add", version=1, runtime_spec=None)
        _send_event(dealer, models.FUNCTION_REGISTERED, "n0", event.model_dump(mode="json"))
        dealer.recv_multipart()  # drain ack

        stream_name, event_type, _data = appender.appended[0]
        assert stream_name == "functions-add-1"
        assert event_type == models.FUNCTION_REGISTERED
    finally:
        dealer.close()
        server.stop()
