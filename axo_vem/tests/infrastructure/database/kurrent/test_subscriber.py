import json
import threading
from dataclasses import dataclass

import mongomock

from axo_shared.events import models

from axo_vem.application.projector.dispatcher import apply_event
from axo_vem.application.projector.handlers import ProjectorHandlers
from axo_vem.infrastructure.database.kurrent.subscriber import KurrentSubscriber, _STREAM_NAME_PREFIXES
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository
from axo_vem.infrastructure.database.mongo.bucket_repository import (
    MongoBucketRepository,
    MongoDataItemRepository,
)
from axo_vem.infrastructure.database.mongo.checkpoint_store import MongoCheckpointStore
from axo_vem.infrastructure.database.mongo.choreography_repository import MongoChoreographyRepository
from axo_vem.infrastructure.database.mongo.consensus_repository import MongoConsensusRepository
from axo_vem.infrastructure.database.mongo.endpoint_repository import MongoEndpointRepository
from axo_vem.infrastructure.database.mongo.function_repository import MongoFunctionRepository
from axo_vem.infrastructure.database.mongo.job_repository import MongoJobRepository
from axo_vem.infrastructure.database.mongo.user_profile_repository import MongoUserProfileRepository
from axo_vem.infrastructure.database.mongo.virtual_environment_repository import (
    MongoVirtualEnvironmentRepository,
)


@dataclass
class _FakeRecordedEvent:
    type: str
    data: bytes
    commit_position: int


def _fake_event(event_type, event, commit_position):
    return _FakeRecordedEvent(
        type=event_type,
        data=json.dumps(event.model_dump(mode="json")).encode("utf-8"),
        commit_position=commit_position,
    )


def _subscriber(client=None, **subscriber_kwargs):
    db = mongomock.MongoClient()["test"]
    handlers = ProjectorHandlers(
        activity_recorder=MongoActivityRepository(db["unified_activity"]),
        user_profile_repository=MongoUserProfileRepository(db["user_profiles"]),
        virtual_environment_repository=MongoVirtualEnvironmentRepository(db["virtual_environments"]),
        endpoint_repository=MongoEndpointRepository(db["endpoints"]),
        function_repository=MongoFunctionRepository(db["functions"]),
        consensus_recorder=MongoConsensusRepository(db["consensus"]),
        job_repository=MongoJobRepository(db["jobs"]),
        bucket_repository=MongoBucketRepository(db["buckets"]),
        data_item_repository=MongoDataItemRepository(db["bucket_data"]),
        choreography_repository=MongoChoreographyRepository(db["choreographies"]),
    )
    checkpoints = MongoCheckpointStore(db["projector_checkpoints"])
    subscriber = KurrentSubscriber(
        client=client, checkpoint_store=checkpoints,
        on_event=lambda event_type, data: apply_event(handlers, event_type, data),
        **subscriber_kwargs,
    )
    return subscriber, checkpoints, db


def test_apply_record_upserts_and_advances_checkpoint():
    subscriber, checkpoints, db = _subscriber()
    event = models.EndpointStarted(
        endpoint_id="n0", router_bind="tcp://0.0.0.0:5555", pub_bind="tcp://0.0.0.0:5556",
    )
    record = _fake_event(models.ENDPOINT_STARTED, event, commit_position=10)

    subscriber.apply_record(record)

    assert db["endpoints"].find_one({"_id": "n0"}) is not None
    assert checkpoints.get_position() == 10


def test_replaying_the_same_event_is_idempotent():
    subscriber, checkpoints, db = _subscriber()
    event = models.EndpointMetricsReported(endpoint_id="n0", metrics={"queue_depth": 1})
    record = _fake_event(models.ENDPOINT_METRICS_REPORTED, event, commit_position=5)

    subscriber.apply_record(record)
    subscriber.apply_record(record)  # simulate at-least-once redelivery

    assert db["endpoints"].count_documents({}) == 1
    assert checkpoints.get_position() == 5


def test_checkpoint_advances_across_a_sequence_of_events():
    subscriber, checkpoints, _db = _subscriber()
    events = [
        _fake_event(
            models.ENDPOINT_STARTED,
            models.EndpointStarted(endpoint_id="n0", router_bind="a", pub_bind="b"),
            commit_position=1,
        ),
        _fake_event(
            models.ENDPOINT_METRICS_REPORTED,
            models.EndpointMetricsReported(endpoint_id="n0", metrics={}),
            commit_position=2,
        ),
        _fake_event(
            models.FUNCTION_REGISTERED,
            models.FunctionRegistered(endpoint_id="n0", function_id="add", version=1, runtime_spec=None),
            commit_position=3,
        ),
    ]

    for record in events:
        subscriber.apply_record(record)

    assert checkpoints.get_position() == 3


class _FakeSubscription:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def __iter__(self):
        return iter(())


class _FakeKurrentClient:
    def __init__(self):
        self.subscribe_to_all_kwargs = None

    def subscribe_to_all(self, **kwargs):
        self.subscribe_to_all_kwargs = kwargs
        return _FakeSubscription()


def test_run_forever_subscribes_with_prefix_matching_not_regex():
    """Regression test: kurrentdbclient's construct_filter_include_regex()
    joins filter_include as "^" + "|".join(patterns) + "$" -- since "|" has
    the lowest regex precedence, that trailing "$" only binds to the *last*
    pattern, silently turning it into an exact-match ("activity-" would only
    match a stream literally named "activity-", never "activity-<function_id>").
    filter_by_prefix=True must stay set so kurrentdbclient sends these as
    real prefixes instead of building a joined regex at all."""
    client = _FakeKurrentClient()
    subscriber, _checkpoints, _db = _subscriber(client=client)

    subscriber.run_forever()

    assert client.subscribe_to_all_kwargs["filter_by_prefix"] is True
    assert client.subscribe_to_all_kwargs["filter_include"] == _STREAM_NAME_PREFIXES
    assert "activity-" in client.subscribe_to_all_kwargs["filter_include"]


class _StoppableFakeSubscription:
    """Simulates a live subscription that never yields another record until
    told to stop -- .stop() ends the underlying iterator *gracefully* (no
    exception), matching real kurrentdbclient behavior verified against a
    live KurrentDB instance. A naive implementation might assume stop()
    surfaces as a raised/cancelled error instead."""

    def __init__(self):
        self._stop_event = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def __iter__(self):
        return self

    def __next__(self):
        self._stop_event.wait()
        raise StopIteration

    def stop(self):
        self._stop_event.set()


class _FakeMultiCallKurrentClient:
    def __init__(self, subscriptions):
        self._subscriptions = list(subscriptions)
        self.call_count = 0

    def subscribe_to_all(self, **kwargs):
        subscription = self._subscriptions[min(self.call_count, len(self._subscriptions) - 1)]
        self.call_count += 1
        return subscription


def test_watchdog_forced_stop_reconnects_instead_of_silently_exiting():
    """Regression test for a real bug found live: stopping the current
    subscription (as the staleness watchdog does) ends its iterator
    gracefully rather than raising, so run_forever must detect that via the
    _watchdog_triggered flag and reconnect -- not just treat a clean return
    as "the subscription ended, stop the thread" (which silently killed the
    projector thread on a real, verified KurrentDB restart)."""
    first = _StoppableFakeSubscription()
    second = _FakeSubscription()  # empty -- ends the test once reconnected
    client = _FakeMultiCallKurrentClient([first, second])
    subscriber, _checkpoints, _db = _subscriber(client=client, stale_after_seconds=0.05)

    thread = threading.Thread(target=subscriber.run_forever, daemon=True)
    thread.start()
    try:
        assert first._stop_event.wait(timeout=2), "watchdog never force-stopped the stale subscription"
        thread.join(timeout=2)
        assert not thread.is_alive(), "run_forever should have reconnected and then exited via the empty second subscription"
        assert client.call_count == 2, "expected a reconnect: subscribe_to_all should be called twice"
    finally:
        subscriber.stop()
