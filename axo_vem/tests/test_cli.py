import os
import sys

import axo_vem.main as main_module
from axo_vem.cli import main as cli_main


def test_flags_are_injected_into_environ(clean_env, monkeypatch):
    called = []
    monkeypatch.setattr(main_module, "main", lambda: called.append(True))
    monkeypatch.setattr(sys, "argv", [
        "axo-vem",
        "--router-bind", "tcp://0.0.0.0:7000",
        "--log-level", "WARNING",
    ])

    cli_main()

    assert os.environ["AXO_VEM_ROUTER_BIND"] == "tcp://0.0.0.0:7000"
    assert os.environ["AXO_VEM_LOG_LEVEL"] == "WARNING"
    assert called == [True]


def test_env_file_flag_sets_env_var(clean_env, monkeypatch):
    monkeypatch.setattr(main_module, "main", lambda: None)
    monkeypatch.setattr(sys, "argv", ["axo-vem", "--env-file", ".env.dev"])

    cli_main()

    assert os.environ["AXO_VEM_ENV_FILE"] == ".env.dev"


def test_unset_flags_do_not_touch_environ(clean_env, monkeypatch):
    monkeypatch.setattr(main_module, "main", lambda: None)
    monkeypatch.setattr(sys, "argv", ["axo-vem"])

    cli_main()

    assert "AXO_VEM_HTTP_PORT" not in os.environ
    assert "AXO_VEM_ENV_FILE" not in os.environ
