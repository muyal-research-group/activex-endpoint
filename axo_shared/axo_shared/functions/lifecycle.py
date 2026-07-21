from __future__ import annotations

from enum import Enum
from typing import FrozenSet, Tuple


class FunctionState(Enum):
    """The stage a registered function is currently in."""

    REGISTERED = "REGISTERED"
    COLD_START = "COLD_START"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    IDLE = "IDLE"
    EVICTED = "EVICTED"


# Allowed state changes:
#   REGISTERED -> COLD_START -> RUNNING -> COMPLETED or FAILED -> IDLE or EVICTED
#   IDLE -> RUNNING (worker reused) or IDLE -> EVICTED
#   EVICTED -> COLD_START (needs a new worker)
_VALID_TRANSITIONS: FrozenSet[Tuple[FunctionState, FunctionState]] = frozenset(
    {
        (FunctionState.REGISTERED, FunctionState.COLD_START),
        (FunctionState.COLD_START, FunctionState.RUNNING),
        (FunctionState.RUNNING, FunctionState.COMPLETED),
        (FunctionState.RUNNING, FunctionState.FAILED),
        (FunctionState.COMPLETED, FunctionState.IDLE),
        (FunctionState.COMPLETED, FunctionState.EVICTED),
        (FunctionState.FAILED, FunctionState.IDLE),
        (FunctionState.FAILED, FunctionState.EVICTED),
        (FunctionState.IDLE, FunctionState.RUNNING),
        (FunctionState.IDLE, FunctionState.EVICTED),
        (FunctionState.EVICTED, FunctionState.COLD_START),
    }
)


def is_valid_transition(frm: FunctionState, to: FunctionState) -> bool:
    """Checks whether a function is allowed to move from one state to another."""
    return (frm, to) in _VALID_TRANSITIONS
