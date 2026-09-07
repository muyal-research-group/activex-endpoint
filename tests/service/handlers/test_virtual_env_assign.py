from axo_shared import wire
from axo_shared.protocol import Command

from axo_endpoint.service.handlers.virtual_env_assign import VirtualEnvAssignHandler


class _FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, event_type, data):
        self.published.append((event_type, data))


def _handler(active_job_ids, current_virtual_environment_id=None, publisher=None):
    state = {"virtual_environment_id": current_virtual_environment_id}
    return VirtualEnvAssignHandler(
        active_job_ids_provider=lambda: set(active_job_ids),
        get_virtual_environment_id=lambda: state["virtual_environment_id"],
        set_virtual_environment_id=lambda v: state.update(virtual_environment_id=v),
        endpoint_id="n0",
        external_publisher=publisher,
        logger=None,
    ), state


def _command(virtual_environment_id):
    return Command(
        operation=wire.VIRTUAL_ENV_ASSIGN,
        content_type="application/json",
        envelope={"virtual_environment_id": virtual_environment_id},
    )


def test_assign_succeeds_when_idle_and_publishes_assigned_event():
    publisher = _FakePublisher()
    handler, state = _handler(active_job_ids=set(), publisher=publisher)

    result = handler.handle(_command("ve1"))

    assert result.ok is True
    assert state["virtual_environment_id"] == "ve1"
    assert len(publisher.published) == 1
    event_type, data = publisher.published[0]
    assert event_type == "EndpointVirtualEnvironmentAssigned"
    assert data["virtual_environment_id"] == "ve1"
    assert data["endpoint_id"] == "n0"


def test_detach_succeeds_when_idle_and_publishes_detached_event():
    publisher = _FakePublisher()
    handler, state = _handler(active_job_ids=set(), current_virtual_environment_id="ve1", publisher=publisher)

    result = handler.handle(_command(None))

    assert result.ok is True
    assert state["virtual_environment_id"] is None
    event_type, data = publisher.published[0]
    assert event_type == "EndpointVirtualEnvironmentDetached"
    assert data["previous_virtual_environment_id"] == "ve1"


def test_rejects_reassignment_while_jobs_are_active():
    publisher = _FakePublisher()
    handler, state = _handler(active_job_ids={"job-1"}, current_virtual_environment_id="ve1", publisher=publisher)

    result = handler.handle(_command("ve2"))

    assert result.ok is False
    assert result.error_name == "ENDPOINT_BUSY"
    assert state["virtual_environment_id"] == "ve1"  # unchanged
    assert publisher.published == []


def test_works_without_an_external_publisher_configured():
    handler, state = _handler(active_job_ids=set(), publisher=None)

    result = handler.handle(_command("ve1"))

    assert result.ok is True
    assert state["virtual_environment_id"] == "ve1"
