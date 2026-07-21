from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from axo_shared.functions.lifecycle import FunctionState
from axo_shared.functions.params_schema import ParamSpec
from axo_shared.runtime.spec import RuntimeSpec


@dataclass(frozen=True)
class FunctionRecord:
    """The code and metadata for one registered function, at one version.

    function_id is the derived (user_id, virtual_environment_id, name) identity
    used as the storage key's id -- name is a separate, non-unique display
    field (two different users/workspaces may register the same name).

    Never changes after creation — a state change creates a new record.
    """

    code: bytes
    function_id: str
    name: str
    version: int
    created_at: float
    state: FunctionState
    runtime_spec: Optional[RuntimeSpec] = None
    code_format: str = "cloudpickle"
    params_schema: Optional[List[ParamSpec]] = None
