from __future__ import annotations

from option import Err, Ok, Result

from axo_shared.errors import AxoError
from axo_shared.protocol import Command, CommandHandler
from axo_shared import wire
from axo_endpoint.core.consensus.concurrency import SlotDecision


class ConcurrencyClient:
    """Thin facade ContainerFunctionRuntime calls for slot placement/release.

    Built from the same LeaderProxyHandler instances registered as direct
    handlers for CONCURRENCY_SLOT_REQUEST/CONCURRENCY_SLOT_RELEASE, so this
    class doesn't need to know whether this endpoint is currently leader (an
    in-process call) or a follower (a real wire forward) -- LeaderProxyHandler
    already hides that distinction."""

    def __init__(
        self,
        self_id: str,
        slot_request_handler: CommandHandler,
        slot_release_handler: CommandHandler,
    ) -> None:
        self._self_id = self_id
        self._slot_request_handler = slot_request_handler
        self._slot_release_handler = slot_release_handler

    @property
    def self_id(self) -> str:
        return self._self_id

    def request_growth(self, function_id: str, version: int, max_concurrency: int) -> Result[SlotDecision, AxoError]:
        command = Command(
            operation=wire.CONCURRENCY_SLOT_REQUEST,
            content_type="application/json",
            envelope={
                "function_id": function_id, "version": version,
                "max_concurrency": max_concurrency, "requester_id": self._self_id,
            },
        )
        result = self._slot_request_handler.handle(command)
        if not result.ok:
            return Err(AxoError(result.error, context={"error_code": result.error_code, "error_name": result.error_name}))

        action = result.metadata.get("action")
        if action == "granted":
            return Ok(SlotDecision.granted(result.metadata["slot_index"]))
        if action == "place":
            return Ok(SlotDecision.place(result.metadata["target_endpoint_id"]))
        return Ok(SlotDecision.retry())

    def release(self, function_id: str, version: int, slot_index: int) -> None:
        """Fire-and-forget -- the caller doesn't need (and isn't given) the result."""
        command = Command(
            operation=wire.CONCURRENCY_SLOT_RELEASE,
            content_type="application/json",
            envelope={
                "function_id": function_id, "version": version,
                "slot_index": slot_index, "endpoint_id": self._self_id,
            },
        )
        self._slot_release_handler.handle(command)
