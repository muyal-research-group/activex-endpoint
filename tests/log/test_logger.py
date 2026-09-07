import json
import logging

from axo_endpoint.log import DumbLogger, Log


def test_log_import_does_not_reference_lolypos():
    # Regression test for the stray `lolypos.shared.envs.log` import.
    import axo_endpoint.log as log_mod

    assert hasattr(log_mod, "Log")
    assert hasattr(log_mod, "DumbLogger")


def test_dumb_logger_is_a_noop():
    logger = DumbLogger()
    assert logger.debug("x", foo="bar") is None
    assert logger.info({"event": "X"}) is None
    assert logger.warning() is None
    assert logger.error("boom", exc_info=True) is None


def test_disabled_log_attaches_only_null_handler(clean_env):
    logger = Log(name="test-disabled", disabled=True)
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.NullHandler)
    # Must not raise even though no real handler is attached.
    logger.info_event("TEST.EVENT", message="hi")


def test_info_event_emits_parseable_json(clean_env, capsys):
    logger = Log(
        name="test-console",
        disabled=False,
        to_file=False,
        error_log=False,
        use_rich=False,
    )
    logger.info_event("TEST.EVENT", message="hi", foo="bar")

    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["event"] == "TEST.EVENT"
    assert data["message"] == "hi"
    assert data["foo"] == "bar"
    assert data["level"] == "INFO"


def test_to_file_and_error_log_construct_handlers_without_error(clean_env, tmp_path):
    logger = Log(
        name="test-file",
        disabled=False,
        to_file=True,
        error_log=True,
        use_rich=False,
        path=str(tmp_path),
        filename="axo_endpoint",
    )
    # output_path/error_output_path were left as None, exercising the
    # fallback chain down to "{path}/{filename}.log".
    assert (tmp_path / "axo_endpoint.log").exists()
    assert (tmp_path / "axo_endpoint.error.log").exists()
