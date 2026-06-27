import os

import pytest


@pytest.fixture
def clean_log_env(monkeypatch):
    """Strip all AXO_ENDPOINT_LOG_* vars so each test starts from defaults."""
    for key in list(os.environ):
        if key.startswith("AXO_ENDPOINT_LOG_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def clean_endpoint_env(monkeypatch):
    """Strip all AXO_ENDPOINT_* vars except the LOG_* ones (those have their
    own fixture and their own namespace), so Config tests start from
    defaults regardless of the ambient shell environment."""
    for key in list(os.environ):
        if key.startswith("AXO_ENDPOINT_") and not key.startswith("AXO_ENDPOINT_LOG_"):
            monkeypatch.delenv(key, raising=False)
