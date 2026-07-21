from __future__ import annotations

import dataclasses
from typing import Callable, Optional, Union

from option import Result

from axo_endpoint.core.consensus.elector import LeaderElector
from axo_endpoint.core.consensus.errors import LeaderUnreachableError
from axo_endpoint.core.errors import AxoError
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]
ForwardFn = Callable[[str, Command, float], "Result[CommandResult, AxoError]"]


class LeaderProxyHandler(CommandHandler):
    """Wraps a leader-only handler: runs it locally when we are leader,
    otherwise forwards the exact command to whoever currently is and relays
    their reply.

    The original caller never sees a leadership error in the normal case —
    it only ever gets the same CommandResult it would have gotten by talking
    to the leader directly. Forwarding is capped at one hop: a command that
    already carries ``__forwarded__: True`` and still lands on a non-leader
    is rejected rather than forwarded again, so a stale/flapping leader view
    during re-election can't cause a forwarding loop.
    """

    def __init__(
        self,
        inner: CommandHandler,
        elector: LeaderElector,
        self_id: str,
        resolve_leader_rpc_uri: Callable[[str], Optional[str]],
        forward_fn: ForwardFn,
        forward_timeout_seconds: float,
        logger: _Logger = None,
    ) -> None:
        self._inner = inner
        self._elector = elector
        self._self_id = self_id
        self._resolve_leader_rpc_uri = resolve_leader_rpc_uri
        self._forward_fn = forward_fn
        self._forward_timeout_seconds = forward_timeout_seconds
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        """Runs locally when leader; otherwise forwards to the leader and relays its reply."""
        if self._elector.is_leader(self._self_id):
            return self._inner.handle(command)

        if command.envelope.get("__forwarded__"):
            return self._forward_failure(
                command, LeaderUnreachableError("leader view unresolved after one forward hop")
            )

        leader_id = next(iter(self._elector.current_view().leader_ids), "")
        rpc_uri = self._resolve_leader_rpc_uri(leader_id)
        if rpc_uri is None:
            return self._forward_failure(
                command,
                LeaderUnreachableError(
                    f"no known address for leader {leader_id!r}", context={"leader_id": leader_id}
                ),
            )

        forwarded = dataclasses.replace(
            command, envelope={**command.envelope, "__forwarded__": True}
        )
        result = self._forward_fn(rpc_uri, forwarded, self._forward_timeout_seconds)
        if result.is_err:
            return self._forward_failure(
                command,
                LeaderUnreachableError(
                    str(result.unwrap_err()), context={"leader_id": leader_id, "rpc_uri": rpc_uri}
                ),
            )

        self._logger.info_event(
            Event.Consensus.REQUEST_FORWARDED,
            component=Component.HANDLER_LEADER_PROXY,
            leader_id=leader_id,
            operation=command.operation,
        )
        return result.unwrap()

    def _forward_failure(self, command: Command, err: LeaderUnreachableError) -> CommandResult:
        self._logger.warning_event(
            Event.Consensus.REQUEST_FORWARD_FAILED,
            component=Component.HANDLER_LEADER_PROXY,
            operation=command.operation,
            **err.to_dict(),
        )
        return CommandResult.from_error(err)
