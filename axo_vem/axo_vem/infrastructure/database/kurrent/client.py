from __future__ import annotations

from kurrentdbclient import KurrentDBClient


def build_kurrent_client(uri: str) -> KurrentDBClient:
    """Constructs a real KurrentDBClient connected to the given URI."""
    return KurrentDBClient(uri)
