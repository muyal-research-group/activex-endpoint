import pytest
from option import Ok

from axo_shared.protocol import CommandResult

import axo_vem.application.choreography.cancel_choreography_run as cancel_choreography_run_module
from axo_vem.application.choreography.cancel_choreography_run import CancelChoreographyRunUseCase
from axo_vem.domain.choreography.choreography import Choreography
from axo_vem.domain.choreography.run import ChoreographyRun
from axo_vem.domain.errors import ConflictError, NotFoundError
from axo_vem.domain.events import models


class _FakeChoreographyRepository:
    def __init__(self, choreography=None):
        self._choreography = choreography

    def get(self, choreography_id):
        if self._choreography is not None and self._choreography.choreography_id == choreography_id:
            return self._choreography
        return None


class _FakeRunRepository:
    def __init__(self, run=None):
        self._run = run
        self.saved = []

    def get(self, run_id):
        return self._run if self._run is not None and self._run.run_id == run_id else None

    def save(self, run):
        self.saved.append(run)


class _FakeRunUseCase:
    def __init__(self, stop_flags=None, live_jobs_by_run=None):
        self.stop_flags = stop_flags or {}
        self.live_jobs_by_run = live_jobs_by_run or {}


class _FakeStopFlag:
    def __init__(self):
        self.was_set = False

    def set(self):
        self.was_set = True


def _choreography(choreography_id="c1", owner="user-1"):
    return Choreography(
        choreography_id=choreography_id, name="pipeline", owner_user_id=owner,
        graph=models.ChoreographyGraph(nodes=[], edges=[]),
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )


def _run(run_id="run1", choreography_id="c1", status="running"):
    return ChoreographyRun(run_id=run_id, choreography_id=choreography_id, status=status)


def test_execute_raises_not_found_for_unknown_run():
    use_case = CancelChoreographyRunUseCase(
        _FakeChoreographyRepository(), _FakeRunRepository(None), _FakeRunUseCase(),
    )

    with pytest.raises(NotFoundError):
        use_case.execute(run_id="run1", current_user_id="user-1")


def test_execute_raises_conflict_when_run_is_not_active():
    run = _run(status="completed")
    use_case = CancelChoreographyRunUseCase(
        _FakeChoreographyRepository(_choreography()), _FakeRunRepository(run), _FakeRunUseCase(),
    )

    with pytest.raises(ConflictError):
        use_case.execute(run_id="run1", current_user_id="user-1")


def test_execute_succeeds_even_when_choreography_lookup_returns_none():
    """Pins current behavior, not an endorsement: if the choreography has
    since been hard-purged, assert_owner is skipped entirely and cancel
    proceeds without an ownership check. Worth naming explicitly as a
    possible follow-up authorization gap rather than silently assuming it's
    fine forever."""
    run = _run(status="running")
    run_repository = _FakeRunRepository(run)
    use_case = CancelChoreographyRunUseCase(
        _FakeChoreographyRepository(None), run_repository, _FakeRunUseCase(),
    )

    result = use_case.execute(run_id="run1", current_user_id="anyone-at-all")

    assert result["status"] == "cancelled"
    assert run_repository.saved[-1].status == "cancelled"


def test_execute_succeeds_when_no_stop_flag_is_registered_for_the_run():
    run = _run(status="running")
    run_repository = _FakeRunRepository(run)
    use_case = CancelChoreographyRunUseCase(
        _FakeChoreographyRepository(_choreography()), run_repository, _FakeRunUseCase(stop_flags={}),
    )

    result = use_case.execute(run_id="run1", current_user_id="user-1")

    assert result["status"] == "cancelled"


def test_execute_sends_job_cancel_for_every_live_job_and_marks_run_cancelled(monkeypatch):
    run = _run(status="running")
    run_repository = _FakeRunRepository(run)
    stop_flag = _FakeStopFlag()
    run_use_case = _FakeRunUseCase(
        stop_flags={"run1": stop_flag},
        live_jobs_by_run={"run1": {"job-a": "tcp://ep1:5555", "job-b": "tcp://ep2:5555"}},
    )
    use_case = CancelChoreographyRunUseCase(
        _FakeChoreographyRepository(_choreography()), run_repository, run_use_case,
    )

    sent = []

    def fake_send_command(rpc_uri, command, timeout):
        sent.append((rpc_uri, command.operation, command.envelope))
        return Ok(CommandResult(ok=True))

    monkeypatch.setattr(cancel_choreography_run_module, "send_command", fake_send_command)

    result = use_case.execute(run_id="run1", current_user_id="user-1")

    assert stop_flag.was_set is True
    assert result["status"] == "cancelled"
    assert result["finished_at"] is not None
    assert {(uri, op, envelope["job_id"]) for uri, op, envelope in sent} == {
        ("tcp://ep1:5555", "JOB_CANCEL", "job-a"),
        ("tcp://ep2:5555", "JOB_CANCEL", "job-b"),
    }
