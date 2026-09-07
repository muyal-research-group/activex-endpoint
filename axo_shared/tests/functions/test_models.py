from axo_shared.functions.lifecycle import FunctionState
from axo_shared.functions.models import FunctionRecord


def test_code_format_defaults_to_cloudpickle():
    record = FunctionRecord(
        code=b"", function_id="add", name="add", version=1, created_at=0.0, state=FunctionState.REGISTERED,
    )
    assert record.code_format == "cloudpickle"


def test_code_format_can_be_set_to_source():
    record = FunctionRecord(
        code=b"def add(params, ctx): ...", function_id="add", name="add", version=1,
        created_at=0.0, state=FunctionState.REGISTERED, code_format="source",
    )
    assert record.code_format == "source"
