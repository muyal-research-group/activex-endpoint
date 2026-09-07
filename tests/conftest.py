import os

import pytest


@pytest.fixture
def clean_env(monkeypatch):
    """Strip all AXO_ENDPOINT_* vars so each test starts from defaults."""
    for key in list(os.environ):
        if key.startswith("AXO_ENDPOINT_"):
            monkeypatch.delenv(key, raising=False)
