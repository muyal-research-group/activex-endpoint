from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

ParamType = Literal["string", "number", "boolean", "json", "data_ref"]


@dataclass(frozen=True)
class ParamSpec:
    """Declares one JOB_SUBMIT parameter a registered function accepts.

    `data_ref` means the value is a reference into registered bucket data
    (an IORef-shaped dict: kind/location/format) rather than an inline
    value -- the function passes it straight to dataio.read(IORef(**value)).
    """

    name: str
    type: ParamType = "string"
    required: bool = True
    default: Optional[Any] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ParamSpec":
        return ParamSpec(
            name=d["name"],
            type=d.get("type", "string"),
            required=bool(d.get("required", True)),
            default=d.get("default"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "type": self.type, "required": self.required, "default": self.default}


def parse_params_schema(raw: Optional[List[Dict[str, Any]]]) -> List[ParamSpec]:
    """Deserializes a params_schema list from a plain dict list (e.g. from the wire envelope)."""
    if not raw:
        return []
    return [ParamSpec.from_dict(d) for d in raw]


def params_schema_to_list(schema: Optional[List[ParamSpec]]) -> List[Dict[str, Any]]:
    """Serializes a params_schema to a plain dict list for envelope/storage."""
    if not schema:
        return []
    return [spec.to_dict() for spec in schema]
