from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Dict, Optional, Union

from axo_endpoint.core.errors import DispatcherClosedError, QueueFullError, UnknownOperationError
from axo_endpoint.core.network.protocol import Command, CommandDispatcher, CommandHandler, CommandResult
from axo_endpoint.log import DumbLogger, Log

_Logger = Union[Log, DumbLogger]


@dataclass(frozen=True)
class _WorkItem:
    command: Command
    handler: CommandHandler
    future: "Future[CommandResult]"


class InMemoryCommandDispatcher(CommandDispatcher):
    """Runs commands on a small pool of worker threads, with a limited-size queue."""

    def __init__(self, max_queue_size: int, worker_count: int, logger: _Logger = None) -> None:
        self._handlers: Dict[str, CommandHandler] = {}
        self._queue: "queue.Queue[Optional[_WorkItem]]" = queue.Queue(maxsize=max_queue_size)
        self._lock = threading.Lock()
        self._closed = False
        self._metrics = {"submitted": 0, "completed": 0, "failed": 0}
        self._logger: _Logger = logger or DumbLogger()
        self._workers = [
            threading.Thread(target=self._run_worker, daemon=True) for _ in range(worker_count)
        ]
        for worker in self._workers:
            worker.start()

    def register_handler(self, operation: str, handler: CommandHandler) -> None:
        """Registers which handler should process a given operation."""
        self._handlers[operation] = handler

    def submit(self, command: Command) -> CommandResult:
        """Submits a command for processing and waits for the result."""
        if self._closed:
            err = DispatcherClosedError("dispatcher is closed", context={"operation": command.operation})
            self._logger.debug_event(
                "DISPATCHER.CLOSED",
                component="dispatcher",
                operation=command.operation,
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        handler = self._handlers.get(command.operation)
        if handler is None:
            err = UnknownOperationError(
                f"no handler registered for '{command.operation}'",
                context={"operation": command.operation},
            )
            self._logger.debug_event(
                "DISPATCHER.UNKNOWN_OPERATION",
                component="dispatcher",
                operation=command.operation,
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        future: "Future[CommandResult]" = Future()
        try:
            self._queue.put_nowait(_WorkItem(command=command, handler=handler, future=future))
        except queue.Full:
            err = QueueFullError("queue is at capacity", context={"operation": command.operation})
            self._logger.debug_event(
                "DISPATCHER.QUEUE_FULL",
                component="dispatcher",
                operation=command.operation,
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        with self._lock:
            self._metrics["submitted"] += 1

        result = future.result()
        with self._lock:
            if result.ok:
                self._metrics["completed"] += 1
            else:
                self._metrics["failed"] += 1
        return result

    def metrics(self) -> Dict[str, int]:
        """Returns counts of submitted, completed, and failed commands, plus the current queue size."""
        with self._lock:
            snapshot = dict(self._metrics)
        snapshot["queue_depth"] = self._queue.qsize()
        return snapshot

    def close(self) -> None:
        """Stops all worker threads, letting them finish their current work first."""
        self._closed = True
        for _ in self._workers:
            self._queue.put(None)
        for worker in self._workers:
            worker.join()

    def _run_worker(self) -> None:
        """Repeatedly takes the next command off the queue and runs its handler."""
        while True:
            item = self._queue.get()
            if item is None:
                break
            try:
                result = item.handler.handle(item.command)
            except Exception as exc:  # noqa: BLE001 - never let a handler bug escape as a raised exception
                self._logger.debug_event(
                    "DISPATCHER.HANDLER_EXC",
                    component="dispatcher",
                    operation=item.command.operation,
                    error_message=str(exc),
                )
                result = CommandResult(ok=False, error=str(exc))
            item.future.set_result(result)
