import dataclasses

import pytest
from option import Err, Ok

from axo_endpoint.core.runtime import (
    FunctionRuntime,
    FunctionRuntimeError,
    InvocationContext,
    InvocationHandle,
)
from axo_endpoint.core.storage import StorageKey


def test_invocation_handle_equality_and_immutability():
    a = InvocationHandle(job_id="j1", function_id="add_one")
    b = InvocationHandle(job_id="j1", function_id="add_one")
    assert a == b
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.job_id = "other"


def test_invocation_handle_has_no_process_concepts():
    handle = InvocationHandle(job_id="j1", function_id="add_one")
    field_names = {f.name for f in dataclasses.fields(handle.__class__)}
    assert field_names == {"job_id", "function_id", "version", "started_at"}
    assert not hasattr(handle, "pid")
    assert not hasattr(handle, "process")


def test_invocation_handle_version_and_started_at_default_to_none():
    handle = InvocationHandle(job_id="j1", function_id="add_one")
    assert handle.version is None
    assert handle.started_at is None


def test_invocation_context_equality_and_immutability():
    a = InvocationContext(job_id="j1", scratch_dir="/tmp/axo_endpoint/scratch/j1")
    b = InvocationContext(job_id="j1", scratch_dir="/tmp/axo_endpoint/scratch/j1")
    assert a == b
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.scratch_dir = "/other"


def test_invocation_context_warn_accumulates_without_mutating_the_frozen_fields():
    ctx = InvocationContext(job_id="j1", scratch_dir="/tmp/axo_endpoint/scratch/j1")
    assert ctx.warnings == []
    ctx.warn("first")
    ctx.warn("second")
    assert ctx.warnings == ["first", "second"]


def test_invocation_context_warnings_are_not_shared_between_instances():
    a = InvocationContext(job_id="a", scratch_dir="/tmp/a")
    b = InvocationContext(job_id="b", scratch_dir="/tmp/b")
    a.warn("only on a")
    assert b.warnings == []


def test_function_runtime_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        FunctionRuntime()


class _EchoRuntime(FunctionRuntime):
    """Trivial fake proving the ABC is satisfiable with minimal ceremony."""

    def invoke(self, function_ref, job_id, params):
        if "fail" in params:
            return Err(FunctionRuntimeError("boom"))
        return Ok(InvocationHandle(job_id=job_id, function_id=function_ref.id))

    def cancel(self, job_id):
        return False


def test_echo_runtime_accepts_invocation():
    runtime = _EchoRuntime()
    result = runtime.invoke(StorageKey(id="add_one"), "j1", {})
    assert result.is_ok
    assert result.unwrap() == InvocationHandle(job_id="j1", function_id="add_one")


def test_echo_runtime_can_reject_invocation():
    runtime = _EchoRuntime()
    result = runtime.invoke(StorageKey(id="add_one"), "j1", {"fail": True})
    assert result.is_err
    assert isinstance(result.unwrap_err(), FunctionRuntimeError)
