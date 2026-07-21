from axo_shared.protocol import Command, CommandResult
from axo_shared import wire


def test_command_round_trips_through_encode_decode():
    command = Command(
        operation=wire.JOB_SUBMIT,
        content_type="application/json",
        envelope={"function_name": "add", "function_version": 1, "params": {"a": 1}},
        payload=b"extra-bytes",
    )

    frames = wire.encode_command(command)
    result = wire.decode_command(frames)

    assert result.is_ok
    assert result.unwrap() == command


def test_command_result_round_trips_through_encode_decode():
    result_value = CommandResult(ok=True, payload=b"x", error="", metadata={"job_id": "j1", "status": "QUEUED"})

    frames = wire.encode_command_result(result_value)
    decoded = wire.decode_command_result(frames)

    assert decoded.is_ok
    assert decoded.unwrap() == result_value


def test_decode_command_with_wrong_frame_count_returns_err():
    result = wire.decode_command([b"only", b"two"])
    assert result.is_err


def test_decode_command_with_malformed_envelope_json_returns_err():
    frames = [b"PING", b"application/json", b"not-json{{{", b""]
    result = wire.decode_command(frames)
    assert result.is_err


def test_decode_command_result_with_wrong_frame_count_returns_err():
    result = wire.decode_command_result([b"1"])
    assert result.is_err


def test_decode_command_result_with_malformed_metadata_json_returns_err():
    frames = [b"1", b"", b"not-json{{{", b""]
    result = wire.decode_command_result(frames)
    assert result.is_err


def test_operation_constants_are_distinct():
    constants = [wire.PING, wire.FUNCTION_REGISTER, wire.JOB_SUBMIT, wire.JOB_RESULT, wire.METRICS]
    assert len(constants) == len(set(constants))
