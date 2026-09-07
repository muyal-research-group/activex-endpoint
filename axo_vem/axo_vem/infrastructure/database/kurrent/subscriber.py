from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, Union

from axo_vem.infrastructure.database.kurrent.types import RecordedEventLike
from axo_vem.infrastructure.database.mongo.checkpoint_store import MongoCheckpointStore
from axo_vem.infrastructure.resilience.errors import classify_kurrent_error
from axo_vem.infrastructure.resilience.retry import retry_with_backoff
from axo_vem.log import DumbLogger, Log
from axo_vem.log.catalog import Component, Event

_Logger = Union[Log, DumbLogger]

# One literal prefix per stream category this taxonomy writes to -- matched
# against stream_name (filter_by_stream_name=True, filter_by_prefix=True), not
# event type, so unrelated streams (Kurrent's own system streams, anything
# else ever appended here) are never delivered to this subscription at all.
#
# Deliberately NOT passed as regex via filter_include without
# filter_by_prefix=True: kurrentdbclient's construct_filter_include_regex()
# joins a pattern list as "^" + "|".join(patterns) + "$" -- since "|" has the
# lowest regex precedence, that trailing "$" only binds to the *last* pattern
# in the list, silently turning it into an exact-match instead of a prefix
# match (e.g. "activity-" would only match a stream literally named
# "activity-", never "activity-<function_id>"). filter_by_prefix=True sends
# these as real prefixes instead, sidestepping that footgun entirely.
_STREAM_NAME_PREFIXES = [
    "endpoints-", "functions-", "consensus-", "activity-",
    "user-profiles-", "virtual-environments-", "buckets-", "choreographies-",
]

OnEvent = Callable[[str, Dict[str, Any]], None]


class KurrentSubscriber:
    """Catch-up-subscribes to Kurrent's $all stream (filtered to just this
    taxonomy's stream prefixes), decodes each record's bytes to a dict, and
    invokes an injected on_event(event_type, data) callback for the
    application layer to dispatch -- see application/projector/dispatcher.py.
    Advances its checkpoint after each successfully-handled event. Runs in
    its own background thread from server.py, alongside the ingestion
    ROUTER and FastAPI.

    Replaces the subscription/decode/checkpoint half of the former
    projector/projector.py's Projector class; the event-routing half moved
    to application/projector/dispatcher.py.
    """

    def __init__(
        self,
        client: Any,
        checkpoint_store: MongoCheckpointStore,
        on_event: OnEvent,
        logger: _Logger = None,
        max_attempts: int = 10,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
        stale_after_seconds: float = 60.0,
    ) -> None:
        self._client = client
        self._checkpoints = checkpoint_store
        self._on_event = on_event
        self._stopped = False
        self._logger: _Logger = logger or DumbLogger()
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        # A gRPC streaming subscription can go silently idle after a
        # network disruption without ever raising -- e.g. verified live:
        # stopping and restarting the KurrentDB container mid-session left
        # an established subscription blocked forever, never erroring, so
        # nothing ever triggered a reconnect. This watchdog force-cancels
        # (and reconnects) a subscription that hasn't delivered anything in
        # stale_after_seconds, as a backstop alongside the exception-based
        # retry above for outright connection failures.
        self._stale_after_seconds = stale_after_seconds
        self._last_activity_at = time.monotonic()
        self._current_subscription: Any = None
        self._watchdog_triggered = False

    def stop(self) -> None:
        self._stopped = True
        if self._current_subscription is not None:
            self._current_subscription.stop()

    def apply_record(self, record: RecordedEventLike) -> None:
        """Applies one already-received event: decode -> on_event -> advance
        checkpoint. The only method exercised by unit tests -- run_forever
        below is a thin, untested-by-design wrapper around the real
        subscribe_to_all gRPC call (verifiable only against a real Kurrent
        instance)."""
        data = json.loads(record.data.decode("utf-8"))
        self._on_event(record.type, data)
        self._checkpoints.set_position(record.commit_position)

    def run_forever(self) -> None:
        """Connects and consumes, reconnecting with capped exponential
        backoff (via retry_with_backoff) if the connection is lost or never
        comes up in the first place -- e.g. KurrentDB not yet accepting
        connections when this thread starts. After max_attempts consecutive
        *unexpected* failures, logs GIVING_UP and returns (this daemon
        thread then stays dead until the process is restarted -- matches
        the pre-existing behavior, just with visibility instead of a
        silent stderr traceback).

        Wrapped in an outer loop: a watchdog-forced reconnect (see
        _watchdog_loop) is expected, healthy behavior, not a failure, so it
        resets the retry budget instead of counting against max_attempts --
        otherwise a long-running, perfectly healthy process would
        eventually hit GIVING_UP purely from accumulated periodic
        stale-connection recycles."""
        watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
        watchdog.start()

        def on_attempt_failed(attempt: int, exc: Exception) -> None:
            error_code, description = classify_kurrent_error(exc)
            self._logger.warning_event(
                Event.Projector.RECONNECTING,
                component=Component.PROJECTOR,
                attempt=attempt,
                max_attempts=self._max_attempts,
                error_code=error_code,
                description=description,
            )

        while not self._stopped:
            try:
                should_reconnect = retry_with_backoff(
                    self._connect_and_consume,
                    max_attempts=self._max_attempts,
                    base_delay_seconds=self._base_delay_seconds,
                    max_delay_seconds=self._max_delay_seconds,
                    on_attempt_failed=on_attempt_failed,
                )
            except Exception as exc:
                error_code, description = classify_kurrent_error(exc)
                self._logger.error_event(
                    Event.Projector.GIVING_UP,
                    component=Component.PROJECTOR,
                    max_attempts=self._max_attempts,
                    error_code=error_code,
                    description=description,
                )
                return
            if not should_reconnect:
                return  # clean shutdown, or the subscription ended on its own

    def _watchdog_loop(self) -> None:
        """Force-cancels the current subscription if it hasn't delivered
        anything in stale_after_seconds -- the backstop for a subscription
        that goes silently idle without ever raising. Polls at a fraction
        of stale_after_seconds so the check itself stays responsive."""
        poll_interval = max(1.0, min(5.0, self._stale_after_seconds / 3))
        while not self._stopped:
            time.sleep(poll_interval)
            if self._stopped or self._current_subscription is None:
                continue
            idle_for = time.monotonic() - self._last_activity_at
            if idle_for > self._stale_after_seconds:
                self._logger.warning_event(
                    Event.Projector.STALE_RECONNECT,
                    component=Component.PROJECTOR,
                    idle_seconds=round(idle_for, 1),
                )
                self._watchdog_triggered = True
                self._current_subscription.stop()

    def _connect_and_consume(self) -> bool:
        """One connect-and-consume attempt -- raises on any *unexpected*
        connection-level failure (subscribe_to_all itself, or the iteration
        dropping mid-stream) for run_forever's retry loop to catch. Returns
        True only when a watchdog-forced cancellation was caught and
        swallowed here (expected, not a failure -- see run_forever's
        docstring), signaling the outer loop to reconnect immediately;
        False otherwise (clean shutdown, or the subscription's iteration
        ending on its own -- doesn't happen against a real live
        subscription, but if it ever did, stopping rather than busy-looping
        is the safe default). Per-record apply failures are handled
        separately below and never escape this method, since those are
        data/logic errors, not connection errors."""
        if self._stopped:
            return False
        t0 = time.monotonic()
        position = self._checkpoints.get_position()
        subscription = self._client.subscribe_to_all(
            commit_position=position,
            filter_include=_STREAM_NAME_PREFIXES,
            filter_by_stream_name=True,
            filter_by_prefix=True,
        )
        self._current_subscription = subscription
        self._last_activity_at = time.monotonic()
        self._logger.info_event(
            Event.Projector.SUBSCRIBED,
            component=Component.PROJECTOR,
            from_position=position,
            duration_ms=round((time.monotonic() - t0) * 1000, 2),
        )
        try:
            with subscription:
                for record in subscription:
                    self._last_activity_at = time.monotonic()
                    if self._stopped:
                        subscription.stop()
                        return False
                    try:
                        self.apply_record(record)
                    except Exception as exc:
                        self._logger.error_event(
                            Event.Projector.APPLY_FAILED,
                            component=Component.PROJECTOR,
                            commit_position=record.commit_position,
                            error=str(exc),
                        )
        except Exception:
            if self._watchdog_triggered:
                self._watchdog_triggered = False
                return True  # expected -- run_forever's outer loop reconnects fresh
            raise
        finally:
            self._current_subscription = None

        # subscription.stop() ends the iterator gracefully (no exception) --
        # verified live, not just via reading kurrentdbclient's source -- so
        # a watchdog-forced stop must also be detected here, not only in the
        # except branch above, or the outer loop wrongly treats a forced
        # reconnect as "the subscription ended, stop the thread".
        if self._watchdog_triggered:
            self._watchdog_triggered = False
            return True
        return False
