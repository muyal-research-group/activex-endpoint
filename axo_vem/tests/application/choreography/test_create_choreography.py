from axo_vem.application.choreography.create_choreography import CreateChoreographyUseCase
from axo_vem.domain.choreography.choreography import stream_name
from axo_vem.domain.events import models


class _FakeEventPublisher:
    def __init__(self):
        self.appended = []

    def append_to_stream(self, stream_name, event_type, data):
        self.appended.append((stream_name, event_type, data))


def _graph():
    return models.ChoreographyGraph(
        nodes=[models.ChoreographyNode(node_id="n1", kind="function", position={"x": 0.0, "y": 0.0})],
        edges=[],
    )


def test_execute_builds_and_appends_choreography_created_event():
    publisher = _FakeEventPublisher()
    use_case = CreateChoreographyUseCase(publisher)
    graph = _graph()

    result = use_case.execute(name="pipeline", owner_user_id="user-1", graph=graph)

    assert result["name"] == "pipeline"
    assert result["owner_user_id"] == "user-1"
    assert len(publisher.appended) == 1
    stream, event_type, data = publisher.appended[0]
    assert stream == stream_name(result["choreography_id"])
    assert event_type == models.CHOREOGRAPHY_CREATED
    assert data == result


def test_execute_mints_a_fresh_choreography_id_each_call():
    publisher = _FakeEventPublisher()
    use_case = CreateChoreographyUseCase(publisher)
    graph = _graph()

    first = use_case.execute(name="pipeline", owner_user_id="user-1", graph=graph)
    second = use_case.execute(name="pipeline", owner_user_id="user-1", graph=graph)

    assert first["choreography_id"] != second["choreography_id"]
