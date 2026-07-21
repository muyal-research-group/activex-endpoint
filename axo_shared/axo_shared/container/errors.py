from __future__ import annotations


class ContainerSpawnError(Exception):
    """Raised by ContainerSpawner on any Docker/Swarm SDK failure. Local to
    axo_shared rather than reusing axo_endpoint.core.errors.ContainerError --
    dependency direction only runs axo_endpoint -> axo_shared, never the
    reverse, so axo_shared cannot import from axo_endpoint. Callers
    (e.g. axo_endpoint's ContainerSummoner) translate this back to their
    own error type at the boundary."""
