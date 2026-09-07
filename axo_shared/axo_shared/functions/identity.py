from __future__ import annotations

import hashlib


def compute_function_id(user_id: str, virtual_environment_id: str, name: str) -> str:
    """Deterministically derives a function's cluster-wide identity from its
    owning user, workspace, and given name. The same triple always yields the
    same id, so re-registering under an already-used name continues that
    function's existing version lineage rather than colliding with (or being
    indistinguishable from) another user/workspace's function of the same
    name. Pure and side-effect free so both axo_vem (real user/VE
    auth context) and the direct-node client (plain caller-supplied
    identifiers, no auth) can derive the same id from the same inputs.
    """
    raw = f"{user_id}:{virtual_environment_id}:{name}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
