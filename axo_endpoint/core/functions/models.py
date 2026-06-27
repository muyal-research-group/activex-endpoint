from __future__ import annotations

from dataclasses import dataclass

from axo_endpoint.core.functions.lifecycle import FunctionState


@dataclass(frozen=True)
class FunctionRecord:
    """The code and metadata for one registered function, at one version.

    Never changes after creation — a state change creates a new record.
    """

    code: bytes
    name: str
    version: int
    created_at: float
    state: FunctionState
