from __future__ import annotations

from axo_endpoint.core.network.protocol import Command, CommandHandler, CommandResult


class PingHandler(CommandHandler):
    """Checks whether the endpoint is alive."""

    def handle(self, command: Command) -> CommandResult:
        """Always replies that the endpoint is alive."""
        return CommandResult(ok=True)
