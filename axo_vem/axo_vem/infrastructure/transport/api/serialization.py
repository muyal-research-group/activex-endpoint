from __future__ import annotations

from typing import Any, Dict


def strip_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Drops Mongo's _id field before returning a document over HTTP -- the
    natural key (endpoint_id, function_id:version, term) is already duplicated
    as a plain field on every document these routes read, so nothing is lost.
    Moved verbatim from api/serialization.py."""
    return {k: v for k, v in doc.items() if k != "_id"}
