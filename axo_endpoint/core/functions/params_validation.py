from __future__ import annotations

from typing import Any, Dict, List

from option import Err, Ok, Result

from axo_endpoint.core.errors import InvalidFieldError
from axo_shared.functions.params_schema import ParamSpec


def _type_matches(value: Any, param_type: str) -> bool:
    if param_type == "string":
        return isinstance(value, str)
    if param_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if param_type == "boolean":
        return isinstance(value, bool)
    if param_type == "json":
        return True
    if param_type == "data_ref":
        return isinstance(value, dict) and isinstance(value.get("kind"), str) and isinstance(value.get("location"), str)
    return False


def validate_and_fill_params(
    schema: List[ParamSpec], params: Dict[str, Any]
) -> Result[Dict[str, Any], InvalidFieldError]:
    """Validates a JOB_SUBMIT params dict against a function's declared
    params_schema: fills in defaults for missing optional fields, type-checks
    every declared field that's present, and rejects both missing-required
    fields and any key not declared in the schema (a strict whitelist once a
    schema exists). Callers must skip this entirely for an empty schema --
    that's the "accept an arbitrary blob" case, preserved for functions
    registered before params_schema existed."""
    declared_names = {spec.name for spec in schema}
    unknown = set(params.keys()) - declared_names
    if unknown:
        return Err(InvalidFieldError(
            f"unknown params not declared in params_schema: {sorted(unknown)}",
            context={"unknown_fields": sorted(unknown)},
        ))

    filled: Dict[str, Any] = {}
    for spec in schema:
        if spec.name not in params:
            if spec.required and spec.default is None:
                return Err(InvalidFieldError(
                    f"missing required param '{spec.name}'",
                    context={"field": spec.name},
                ))
            filled[spec.name] = spec.default
            continue

        value = params[spec.name]
        if not _type_matches(value, spec.type):
            return Err(InvalidFieldError(
                f"param '{spec.name}' does not match declared type '{spec.type}'",
                context={"field": spec.name, "expected_type": spec.type},
            ))
        filled[spec.name] = value

    return Ok(filled)
