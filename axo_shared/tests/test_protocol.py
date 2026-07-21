import dataclasses

import pytest

from axo_shared.protocol import Command, CommandDispatcher, CommandHandler, CommandResult


def test_command_is_frozen_and_supports_equality():
    a = Command(operation="PING", content_type="application/json", envelope={})
    b = Command(operation="PING", content_type="application/json", envelope={})
    assert a == b
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.operation = "OTHER"


def test_command_result_is_frozen_and_supports_equality():
    a = CommandResult(ok=True, payload=b"x")
    b = CommandResult(ok=True, payload=b"x")
    assert a == b
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.ok = False


def test_command_handler_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        CommandHandler()


def test_command_dispatcher_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        CommandDispatcher()


class _EchoHandler(CommandHandler):
    def handle(self, command: Command) -> CommandResult:
        return CommandResult(ok=True, payload=command.payload)


def test_echo_handler_round_trips_payload():
    handler = _EchoHandler()
    command = Command(operation="ECHO", content_type="application/octet-stream", envelope={}, payload=b"hello")
    result = handler.handle(command)
    assert result.ok is True
    assert result.payload == b"hello"


class _DirectDispatcher(CommandDispatcher):
    """Synchronously forwards to one handler — no queuing yet, but proves
    the seam is usable today."""

    def __init__(self, handler: CommandHandler):
        self._handler = handler

    def submit(self, command: Command) -> CommandResult:
        return self._handler.handle(command)


def test_direct_dispatcher_forwards_to_handler():
    dispatcher = _DirectDispatcher(_EchoHandler())
    command = Command(operation="ECHO", content_type="application/octet-stream", envelope={}, payload=b"world")
    result = dispatcher.submit(command)
    assert result.ok is True
    assert result.payload == b"world"
