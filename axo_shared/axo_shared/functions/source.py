from __future__ import annotations

import ast
from typing import Any, Callable


class FunctionSourceError(ValueError):
    pass


def _top_level_function_names(tree: ast.Module) -> set:
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _parse(source: bytes) -> ast.Module:
    try:
        code_text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FunctionSourceError(f"code is not valid UTF-8 text: {exc}") from exc

    try:
        return ast.parse(code_text, filename="<registered_function>")
    except SyntaxError as exc:
        raise FunctionSourceError(f"syntax error in uploaded source: {exc}") from exc


def validate_function_source(source: bytes, function_name: str) -> None:
    tree = _parse(source)
    if function_name not in _top_level_function_names(tree):
        raise FunctionSourceError(
            f"uploaded source does not define a top-level function named '{function_name}'"
        )


def materialize_function_from_source(source: bytes, function_name: str) -> Callable[..., Any]:
    tree = _parse(source)
    if function_name not in _top_level_function_names(tree):
        raise FunctionSourceError(
            f"uploaded source does not define a top-level function named '{function_name}'"
        )

    namespace: dict = {}
    try:
        exec(compile(tree, filename="<registered_function>", mode="exec"), namespace)
    except Exception as exc:
        raise FunctionSourceError(f"error executing uploaded source: {exc}") from exc

    target = namespace.get(function_name)
    if not callable(target):
        raise FunctionSourceError(f"'{function_name}' in the uploaded source is not a function")
    return target
