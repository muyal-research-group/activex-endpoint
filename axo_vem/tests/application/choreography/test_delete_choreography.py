import pytest

from axo_vem.application.choreography.delete_choreography import DeleteChoreographyUseCase
from axo_vem.domain.choreography.choreography import Choreography, stream_name
from axo_vem.domain.errors import ConflictError, NotFoundError, NotOwnerError
from axo_vem.domain.events import models


class _FakeChoreographyRepository:
    def __init__(self, choreography=None):
        self._choreography = choreography

    def get(self, choreography_id):
        if self._choreography is not None and self._choreography.choreography_id == choreography_id:
            return self._choreography
        return None


class _FakeRunRepository:
    def __init__(self, has_active=False):
        self._has_active = has_active

    def has_active_run(self, choreography_id):
        return self._has_active


class _FakeEventPublisher:
    def __init__(self):
        self.appended = []

    def append_to_stream(self, stream_name, event_type, data):
        self.appended.append((stream_name, event_type, data))


def _choreography(choreography_id="c1", owner="user-1"):
    return Choreography(
        choreography_id=choreography_id, name="pipeline", owner_user_id=owner,
        graph=models.ChoreographyGraph(nodes=[], edges=[]),
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )


def test_execute_raises_not_found_for_unknown_choreography():
    use_case = DeleteChoreographyUseCase(_FakeChoreographyRepository(None), _FakeRunRepository(), _FakeEventPublisher())

    with pytest.raises(NotFoundError):
        use_case.execute(choreography_id="c1", current_user_id="user-1")


def test_execute_raises_not_owner_for_foreign_choreography():
    choreography = _choreography(owner="user-1")
    use_case = DeleteChoreographyUseCase(
        _FakeChoreographyRepository(choreography), _FakeRunRepository(), _FakeEventPublisher(),
    )

    with pytest.raises(NotOwnerError):
        use_case.execute(choreography_id="c1", current_user_id="someone-else")


def test_execute_raises_conflict_when_choreography_has_an_active_run():
    choreography = _choreography()
    use_case = DeleteChoreographyUseCase(
        _FakeChoreographyRepository(choreography), _FakeRunRepository(has_active=True), _FakeEventPublisher(),
    )

    with pytest.raises(ConflictError):
        use_case.execute(choreography_id="c1", current_user_id="user-1")


def test_execute_appends_choreography_deleted_event_on_success():
    choreography = _choreography()
    publisher = _FakeEventPublisher()
    use_case = DeleteChoreographyUseCase(
        _FakeChoreographyRepository(choreography), _FakeRunRepository(has_active=False), publisher,
    )

    use_case.execute(choreography_id="c1", current_user_id="user-1")

    assert len(publisher.appended) == 1
    stream, event_type, data = publisher.appended[0]
    assert stream == stream_name("c1")
    assert event_type == models.CHOREOGRAPHY_DELETED
    assert data["choreography_id"] == "c1"
