import pytest

from axo_shared.functions.source import (
    FunctionSourceError,
    materialize_function_from_source,
    validate_function_source,
)


def _source_for(function_name: str) -> bytes:
    return f"def {function_name}(params, ctx):\n    return params['a'] + params['b']\n".encode()


def test_validate_accepts_matching_top_level_function():
    validate_function_source(_source_for("add"), "add")


def test_validate_raises_on_syntax_error():
    with pytest.raises(FunctionSourceError, match="syntax error"):
        validate_function_source(b"def add(params, ctx:\n    pass\n", "add")


def test_validate_raises_when_name_not_defined():
    with pytest.raises(FunctionSourceError, match="does not define a top-level function named 'add'"):
        validate_function_source(_source_for("subtract"), "add")


def test_validate_raises_on_invalid_utf8():
    with pytest.raises(FunctionSourceError, match="not valid UTF-8"):
        validate_function_source(b"\xff\xfe\x00\x01", "add")


def test_validate_does_not_execute_module_body():
    source = b"raise RuntimeError('boom')\ndef add(params, ctx):\n    return 1\n"
    validate_function_source(source, "add")


def test_materialize_returns_callable_matching_name():
    fn = materialize_function_from_source(_source_for("add"), "add")
    assert fn({"a": 2, "b": 3}, None) == 5


def test_materialize_raises_when_name_not_defined():
    with pytest.raises(FunctionSourceError, match="does not define a top-level function named 'add'"):
        materialize_function_from_source(_source_for("subtract"), "add")


def test_materialize_raises_when_decorator_replaces_function_with_non_callable():
    # `add` is still a top-level `def` (passes the AST check) but a decorator
    # can replace the resulting namespace entry with a non-callable value.
    source = b"def _identity(_fn):\n    return 42\n\n@_identity\ndef add(params, ctx):\n    return params['a']\n"
    with pytest.raises(FunctionSourceError, match="is not a function"):
        materialize_function_from_source(source, "add")


def test_materialize_raises_on_error_during_module_exec():
    with pytest.raises(FunctionSourceError, match="error executing uploaded source"):
        materialize_function_from_source(b"raise RuntimeError('boom')\ndef add(params, ctx):\n    return 1\n", "add")


def test_materialize_ignores_other_top_level_definitions():
    source = (
        b"def helper():\n    return 1\n\n"
        b"def add(params, ctx):\n    return params['a'] + params['b']\n"
    )
    fn = materialize_function_from_source(source, "add")
    assert fn({"a": 1, "b": 1}, None) == 2
