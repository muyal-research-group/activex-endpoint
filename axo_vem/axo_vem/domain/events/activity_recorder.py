from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class ActivityRecorder(ABC):
    """Records one already-decoded (event_type, data) pair into the
    cross-cutting activity timeline -- every recognized event type is
    recorded here unconditionally, independent of which aggregate (if any)
    it also targets. See application/projector/dispatcher.py."""

    @abstractmethod
    def record(self, event_type: str, data: Dict[str, Any]) -> None: ...
