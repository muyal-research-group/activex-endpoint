import pytest

from axo_endpoint.core.functions import FunctionState, is_valid_transition


def test_enum_members_exist_with_expected_names():
    expected = {"REGISTERED", "COLD_START", "RUNNING", "COMPLETED", "FAILED", "IDLE", "EVICTED"}
    assert {member.name for member in FunctionState} == expected


@pytest.mark.parametrize(
    "frm,to",
    [
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
    ],
)
def test_documented_valid_edges_return_true(frm, to):
    assert is_valid_transition(frm, to) is True


@pytest.mark.parametrize(
    "frm,to",
    [
        (FunctionState.REGISTERED, FunctionState.RUNNING),  # skips COLD_START
        (FunctionState.EVICTED, FunctionState.RUNNING),  # must cold-start first
        (FunctionState.IDLE, FunctionState.COLD_START),  # warm reuse goes via RUNNING, not COLD_START
        (FunctionState.COLD_START, FunctionState.COLD_START),  # no self-loop
        (FunctionState.REGISTERED, FunctionState.REGISTERED),  # no self-loop
        (FunctionState.COMPLETED, FunctionState.RUNNING),  # must pass through IDLE
    ],
)
def test_undocumented_edges_return_false(frm, to):
    assert is_valid_transition(frm, to) is False
