from __future__ import annotations

from typing import Callable, Optional, Set, Union

from axo_shared.events import models as event_models
from axo_shared.protocol import Command, CommandHandler, CommandResult
from axo_endpoint.core.errors import EndpointBusyError
from axo_endpoint.log import DumbLogger, Log
from axo_endpoint.log.catalog import Component, Event
from axo_endpoint.service.transport.event_publisher import ZmqEventPublisher

_Logger = Union[Log, DumbLogger]


class VirtualEnvAssignHandler(CommandHandler):
    """Handles VIRTUAL_ENV_ASSIGN: reassigns (or clears, if
    virtual_environment_id is None/absent) this endpoint's own
    VirtualEnvironment membership. Direct handler -- not leader-proxied,
    since this is a fact about the receiving endpoint itself, not cluster
    catalog metadata needing Bully-mediated replication.

    Only the endpoint itself has non-stale truth about its own workload, so
    it -- not axo_vem -- gates the change: a command arriving
    while any job is active is rejected outright, never queued or retried.
    """

    def __init__(
        self,
        active_job_ids_provider: Callable[[], Set[str]],
        get_virtual_environment_id: Callable[[], Optional[str]],
        set_virtual_environment_id: Callable[[Optional[str]], None],
        endpoint_id: str,
        external_publisher: Optional[ZmqEventPublisher] = None,
        logger: _Logger = None,
    ) -> None:
        self._active_job_ids_provider = active_job_ids_provider
        self._get_virtual_environment_id = get_virtual_environment_id
        self._set_virtual_environment_id = set_virtual_environment_id
        self._endpoint_id = endpoint_id
        self._external_publisher = external_publisher
        self._logger: _Logger = logger or DumbLogger()

    def handle(self, command: Command) -> CommandResult:
        if self._active_job_ids_provider():
            err = EndpointBusyError(
                "endpoint has active jobs, cannot reassign its virtual environment",
            )
            self._logger.warning_event(
                Event.VirtualEnv.ASSIGN_REJECTED,
                component=Component.HANDLER_VIRTUAL_ENV_ASSIGN,
                **err.to_dict(),
            )
            return CommandResult.from_error(err)

        previous = self._get_virtual_environment_id()
        new_virtual_environment_id = command.envelope.get("virtual_environment_id")
        self._set_virtual_environment_id(new_virtual_environment_id)

        if new_virtual_environment_id is not None:
            self._logger.info_event(
                Event.VirtualEnv.ASSIGNED,
                component=Component.HANDLER_VIRTUAL_ENV_ASSIGN,
                virtual_environment_id=new_virtual_environment_id,
            )
            if self._external_publisher is not None:
                event = event_models.EndpointVirtualEnvironmentAssigned(
                    endpoint_id=self._endpoint_id,
                    virtual_environment_id=new_virtual_environment_id,
                )
                self._external_publisher.publish(
                    event_models.ENDPOINT_VIRTUAL_ENV_ASSIGNED, event.model_dump(mode="json"),
                )
        else:
            self._logger.info_event(
                Event.VirtualEnv.DETACHED,
                component=Component.HANDLER_VIRTUAL_ENV_ASSIGN,
                previous_virtual_environment_id=previous,
            )
            if self._external_publisher is not None and previous is not None:
                event = event_models.EndpointVirtualEnvironmentDetached(
                    endpoint_id=self._endpoint_id,
                    previous_virtual_environment_id=previous,
                )
                self._external_publisher.publish(
                    event_models.ENDPOINT_VIRTUAL_ENV_DETACHED, event.model_dump(mode="json"),
                )

        return CommandResult(ok=True)
