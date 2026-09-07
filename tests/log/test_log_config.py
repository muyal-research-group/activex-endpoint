import logging

from axo_endpoint.config import Config


def test_defaults_with_no_env_vars(clean_env):
    config = Config()
    assert config.AXO_ENDPOINT_LOG_LEVEL == logging.DEBUG
    assert config.AXO_ENDPOINT_LOG_DISABLED is False
    assert config.AXO_ENDPOINT_LOG_TO_FILE is False
    assert config.AXO_ENDPOINT_LOG_PATH == ".axo_endpoint/log"
    assert config.AXO_ENDPOINT_LOG_FILENAME == "axo_endpoint"
    assert config.AXO_ENDPOINT_LOG_OUTPUT_PATH is None
    assert config.AXO_ENDPOINT_LOG_ERROR_OUTPUT_PATH is None
    assert config.AXO_ENDPOINT_LOG_CONSOLE_LEVEL == logging.DEBUG
    assert config.AXO_ENDPOINT_LOG_FILE_LEVEL == logging.INFO
    assert config.AXO_ENDPOINT_LOG_ERROR_FILE is False
    assert config.AXO_ENDPOINT_LOG_ROTATION_WHEN == "midnight"
    assert config.AXO_ENDPOINT_LOG_ROTATION_INTERVAL == 1
    assert config.AXO_ENDPOINT_LOG_JSON_INDENT is None
    assert config.AXO_ENDPOINT_LOG_USE_RICH is False
    assert config.AXO_ENDPOINT_LOG_COLORIZE is True


def test_log_level_env_var(clean_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_LOG_LEVEL", "WARNING")
    assert Config().AXO_ENDPOINT_LOG_LEVEL == logging.WARNING


def test_disabled_truthy_string_variants(clean_env, monkeypatch):
    for value in ["1", "true", "True", "yes", "on"]:
        monkeypatch.setenv("AXO_ENDPOINT_LOG_DISABLED", value)
        assert Config().AXO_ENDPOINT_LOG_DISABLED is True, f"expected True for {value!r}"

    monkeypatch.setenv("AXO_ENDPOINT_LOG_DISABLED", "0")
    assert Config().AXO_ENDPOINT_LOG_DISABLED is False


def test_json_indent_falsy_zero_means_none(clean_env, monkeypatch):
    assert Config().AXO_ENDPOINT_LOG_JSON_INDENT is None

    monkeypatch.setenv("AXO_ENDPOINT_LOG_JSON_INDENT", "0")
    assert Config().AXO_ENDPOINT_LOG_JSON_INDENT is None

    monkeypatch.setenv("AXO_ENDPOINT_LOG_JSON_INDENT", "4")
    assert Config().AXO_ENDPOINT_LOG_JSON_INDENT == 4


def test_malformed_rotation_interval_falls_back_to_default(clean_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_LOG_ROTATION_INTERVAL", "notanint")
    assert Config().AXO_ENDPOINT_LOG_ROTATION_INTERVAL == 1
