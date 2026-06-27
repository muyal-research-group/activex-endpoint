import logging

from axo_endpoint.shared.envs.log import get_log_config


def test_defaults_with_no_env_vars(clean_log_env):
    config = get_log_config()
    assert config["log_level"] == logging.DEBUG
    assert config["disabled"] is False
    assert config["to_file"] is False
    assert config["path"] == ".axo_endpoint/log"
    assert config["filename"] == "axo_endpoint"
    assert config["output_path"] is None
    assert config["error_output_path"] is None
    assert config["console_handler_level"] == logging.DEBUG
    assert config["file_handler_level"] == logging.INFO
    assert config["error_log"] is False
    assert config["when"] == "midnight"
    assert config["interval"] == 1
    assert config["indent"] is None
    assert config["use_rich"] is False
    assert config["colorize"] is True


def test_log_level_env_var(clean_log_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_LOG_LEVEL", "WARNING")
    assert get_log_config()["log_level"] == logging.WARNING


def test_disabled_truthy_string_variants(clean_log_env, monkeypatch):
    for value in ["1", "true", "True", "yes", "on"]:
        monkeypatch.setenv("AXO_ENDPOINT_LOG_DISABLED", value)
        assert get_log_config()["disabled"] is True, f"expected True for {value!r}"

    monkeypatch.setenv("AXO_ENDPOINT_LOG_DISABLED", "0")
    assert get_log_config()["disabled"] is False


def test_json_indent_falsy_zero_means_none(clean_log_env, monkeypatch):
    assert get_log_config()["indent"] is None

    monkeypatch.setenv("AXO_ENDPOINT_LOG_JSON_INDENT", "0")
    assert get_log_config()["indent"] is None

    monkeypatch.setenv("AXO_ENDPOINT_LOG_JSON_INDENT", "4")
    assert get_log_config()["indent"] == 4


def test_malformed_rotation_interval_falls_back_to_default(clean_log_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_LOG_ROTATION_INTERVAL", "notanint")
    assert get_log_config()["interval"] == 1
