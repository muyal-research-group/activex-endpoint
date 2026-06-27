from axo_endpoint.core.network import Command, CommandResult
from axo_endpoint.service.handlers import PingHandler


def test_ping_handler_returns_ok():
    handler = PingHandler()
    result = handler.handle(Command(operation="PING", content_type="application/json", envelope={}))
    assert result == CommandResult(ok=True)
