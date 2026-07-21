from __future__ import annotations

from xolo.client import XoloClient

from axo_vem.config import Config


def build_xolo_client(config: Config) -> XoloClient:
    """Constructs a real XoloClient. Extracted from server.py's previously
    inline XoloClient(...) construction."""
    return XoloClient(
        account_id=config.AXO_VEM_XOLO_ACCOUNT_ID,
        api_key=config.AXO_VEM_XOLO_API_KEY,
        api_url=config.AXO_VEM_XOLO_URI,
    )
