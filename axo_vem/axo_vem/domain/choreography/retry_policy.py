from __future__ import annotations

import random


def next_delay_seconds(
    policy: str, attempt: int, base_seconds: float = 1.0, max_seconds: float = 30.0,
) -> float:
    """The backoff before a node's next retry attempt (1-indexed: attempt=1
    is the delay before the first retry, right after the first failure).

    - "constant": always base_seconds.
    - "exponential_backoff": base_seconds * 2**(attempt-1), uncapped growth
      until max_seconds.
    - "jitter": same exponential growth, but the actual delay is randomized
      within [0, that value] (the common "full jitter" approach) -- so many
      branches retrying at once don't all retry in lockstep.
    """
    if policy == "constant":
        delay = base_seconds
    elif policy == "exponential_backoff":
        delay = base_seconds * (2 ** (attempt - 1))
    elif policy == "jitter":
        delay = random.uniform(0, base_seconds * (2 ** (attempt - 1)))
    else:
        raise ValueError(f"unknown retry_policy: {policy!r}")
    return min(delay, max_seconds)
