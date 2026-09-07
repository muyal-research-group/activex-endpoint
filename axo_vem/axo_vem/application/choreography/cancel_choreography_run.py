from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from axo_shared import wire
from axo_shared.protocol import Command

from axo_vem.application.choreography.run_choreography import RunChoreographyUseCase
from axo_vem.domain.choreography.repository import ChoreographyRepository
from axo_vem.domain.choreography.run import ACTIVE_RUN_STATUSES, CANCELLED
from axo_vem.domain.choreography.run_repository import ChoreographyRunRepository
from axo_vem.domain.errors import ConflictError, NotFoundError
from axo_vem.infrastructure.transport.zmq_command.endpoint_client import send_command


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CancelChoreographyRunUseCase:
    """Stops an active run: flips the orchestrator's stop flag (so no
    further waves get dispatched), sends JOB_CANCEL for every job currently
    in flight (tracked by RunChoreographyUseCase.live_jobs_by_run for
    exactly this purpose), and marks the run cancelled. Anything not yet
    dispatched is simply never reached once the stop flag is observed --
    no separate "drop queued" step needed, unlike axo_endpoint's own
    per-worker queues."""

    def __init__(
        self,
        choreography_repository: ChoreographyRepository,
        run_repository: ChoreographyRunRepository,
        run_use_case: RunChoreographyUseCase,
        command_timeout_seconds: float = 3.0,
    ) -> None:
        self._choreographies = choreography_repository
        self._runs = run_repository
        self._run_use_case = run_use_case
        self._command_timeout_seconds = command_timeout_seconds

    def execute(self, *, run_id: str, current_user_id: str) -> Dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            raise NotFoundError("run not found")
        choreography = self._choreographies.get(run.choreography_id)
        if choreography is not None:
            choreography.assert_owner(current_user_id)
        if run.status not in ACTIVE_RUN_STATUSES:
            raise ConflictError("run is not active")

        stop_flag = self._run_use_case.stop_flags.get(run_id)
        if stop_flag is not None:
            stop_flag.set()

        for job_id, rpc_uri in list(self._run_use_case.live_jobs_by_run.get(run_id, {}).items()):
            send_command(
                rpc_uri,
                Command(operation=wire.JOB_CANCEL, content_type="application/json", envelope={"job_id": job_id}),
                self._command_timeout_seconds,
            )

        run.status = CANCELLED
        run.finished_at = _now_iso()
        self._runs.save(run)
        return run.to_dict()
