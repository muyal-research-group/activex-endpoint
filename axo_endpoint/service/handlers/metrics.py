from __future__ import annotations

from typing import Any, Callable, Dict

from axo_endpoint.core.network.protocol import Command, CommandHandler, CommandResult


class MetricsHandler(CommandHandler):
    """Reports current metrics about the endpoint."""

    def __init__(self, metrics_provider: Callable[[], Dict[str, Any]]) -> None:
        self._metrics_provider = metrics_provider

    def handle(self, command: Command) -> CommandResult:
        """Returns a snapshot of the current metrics."""
        return CommandResult(ok=True, metadata=self._metrics_provider())
