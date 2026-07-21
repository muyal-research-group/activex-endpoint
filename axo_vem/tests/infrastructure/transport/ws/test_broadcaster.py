import asyncio

from axo_vem.infrastructure.transport.ws.broadcaster import Broadcaster


class _FakeWebSocket:
    def __init__(self, fail: bool = False):
        self.sent = []
        self._fail = fail

    async def send_json(self, message):
        if self._fail:
            raise RuntimeError("connection closed")
        self.sent.append(message)


def _run(scenario) -> None:
    """broadcast() schedules delivery via run_coroutine_threadsafe, which
    needs an actually-running loop -- bind_loop() + broadcast() + enough of
    a yield for the scheduled delivery to execute all have to happen inside
    one asyncio.run() call, mirroring how bind_loop() is bound to the real
    uvicorn loop in production."""
    asyncio.run(scenario())


def test_broadcast_before_bind_loop_is_a_noop():
    ws = _FakeWebSocket()

    async def scenario():
        broadcaster = Broadcaster()
        broadcaster.register("buckets", ws)
        broadcaster.broadcast("buckets", {"hello": "world"})
        await asyncio.sleep(0.01)

    _run(scenario)
    assert ws.sent == []


def test_broadcast_delivers_only_to_registered_topic():
    buckets_ws = _FakeWebSocket()
    endpoints_ws = _FakeWebSocket()

    async def scenario():
        broadcaster = Broadcaster()
        broadcaster.bind_loop(asyncio.get_running_loop())
        broadcaster.register("buckets", buckets_ws)
        broadcaster.register("endpoints", endpoints_ws)

        broadcaster.broadcast("buckets", {"name": "b1/df1", "status": "ready"})
        await asyncio.sleep(0.01)

    _run(scenario)
    assert buckets_ws.sent == [{"name": "b1/df1", "status": "ready"}]
    assert endpoints_ws.sent == []


def test_broadcast_reaches_every_connection_on_the_topic():
    ws1 = _FakeWebSocket()
    ws2 = _FakeWebSocket()

    async def scenario():
        broadcaster = Broadcaster()
        broadcaster.bind_loop(asyncio.get_running_loop())
        broadcaster.register("buckets", ws1)
        broadcaster.register("buckets", ws2)

        broadcaster.broadcast("buckets", {"status": "pending"})
        await asyncio.sleep(0.01)

    _run(scenario)
    assert ws1.sent == [{"status": "pending"}]
    assert ws2.sent == [{"status": "pending"}]


def test_unregister_stops_further_delivery():
    ws = _FakeWebSocket()

    async def scenario():
        broadcaster = Broadcaster()
        broadcaster.bind_loop(asyncio.get_running_loop())
        broadcaster.register("buckets", ws)
        broadcaster.unregister("buckets", ws)

        broadcaster.broadcast("buckets", {"status": "ready"})
        await asyncio.sleep(0.01)

    _run(scenario)
    assert ws.sent == []


def test_broadcast_drops_a_connection_that_fails_to_send():
    dead_ws = _FakeWebSocket(fail=True)
    live_ws = _FakeWebSocket()

    async def scenario():
        broadcaster = Broadcaster()
        broadcaster.bind_loop(asyncio.get_running_loop())
        broadcaster.register("buckets", dead_ws)
        broadcaster.register("buckets", live_ws)

        broadcaster.broadcast("buckets", {"status": "pending"})
        await asyncio.sleep(0.01)
        # A second broadcast should only reach the still-live connection --
        # the failed one was dropped by the first delivery attempt.
        broadcaster.broadcast("buckets", {"status": "ready"})
        await asyncio.sleep(0.01)
        assert broadcaster._topics["buckets"] == {live_ws}

    _run(scenario)
    assert live_ws.sent == [{"status": "pending"}, {"status": "ready"}]
