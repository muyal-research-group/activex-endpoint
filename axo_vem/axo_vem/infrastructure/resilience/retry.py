from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

OnAttemptFailed = Callable[[int, Exception], None]


def retry_with_backoff(
    operation: Callable[[], T],
    *,
    max_attempts: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
    on_attempt_failed: OnAttemptFailed,
) -> T:
    """Calls operation(), retrying on any exception with capped exponential
    backoff (base_delay_seconds * 2**attempt, clamped to max_delay_seconds).
    on_attempt_failed(attempt, exc) is invoked before each sleep -- callers
    use it to log a structured retry event. After max_attempts failures the
    last exception is re-raised for the caller to log as fatal and stop,
    rather than retried forever."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return operation()
        except Exception as exc:
            if attempt >= max_attempts:
                raise
            on_attempt_failed(attempt, exc)
            delay = min(base_delay_seconds * (2 ** (attempt - 1)), max_delay_seconds)
            time.sleep(delay)
