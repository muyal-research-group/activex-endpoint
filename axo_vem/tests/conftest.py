import os

import pytest


@pytest.fixture
def clean_env():
    """Strips AXO_VEM_* env vars before and after each test.

    cli.py writes to os.environ directly (not via monkeypatch), so
    monkeypatch's automatic teardown won't revert it -- this fixture
    restores the exact pre-test state explicitly.
    """
    saved = {k: v for k, v in os.environ.items() if k.startswith("AXO_VEM_")}
    for key in saved:
        del os.environ[key]
    yield
    for key in list(os.environ):
        if key.startswith("AXO_VEM_") and key not in saved:
            del os.environ[key]
    os.environ.update(saved)
