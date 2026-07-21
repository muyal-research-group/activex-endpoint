from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

ContainerMode = Literal["docker", "swarm"]


@dataclass(frozen=True)
class RuntimeSpec:
    """Describes how a function should be executed: as a local process or a container."""

    type: Literal["process", "container"] = "process"
    python_version: str = "3.11"
    requirements: List[str] = field(default_factory=list)
    image: Optional[str] = None
    env_vars: Dict[str, str] = field(default_factory=dict)
    idle_ttl_seconds: float = 300.0
    max_invocations: int = 0
    memory_limit_bytes: Optional[int] = None
    cpu_limit: Optional[float] = None
    # How many workers/containers may run this function's jobs in parallel.
    # 1 (default) preserves the historical one-at-a-time behavior.
    max_concurrency: int = 1
    # How long a single job may run before it's treated as timed out
    # (distinct from a crash). 0 = unlimited, same convention as
    # max_invocations.
    max_duration_seconds: float = 0
    # How many times a job may be retried (via normal placement, on a
    # possibly different container) after its container crashes or times
    # out, before being failed for good. 0 = no retries, today's behavior.
    max_retries: int = 3

    @staticmethod
    def from_dict(d: Dict) -> "RuntimeSpec":
        """Deserializes a RuntimeSpec from a plain dict (e.g. from the wire envelope)."""
        memory_limit_bytes = d.get("memory_limit_bytes")
        cpu_limit = d.get("cpu_limit")
        return RuntimeSpec(
            type=d.get("type", "process"),
            python_version=d.get("python_version", "3.11"),
            requirements=list(d.get("requirements", [])),
            image=d.get("image"),
            env_vars=dict(d.get("env_vars", {})),
            idle_ttl_seconds=float(d.get("idle_ttl_seconds", 300.0)),
            max_invocations=int(d.get("max_invocations", 0)),
            memory_limit_bytes=int(memory_limit_bytes) if memory_limit_bytes is not None else None,
            cpu_limit=float(cpu_limit) if cpu_limit is not None else None,
            max_concurrency=int(d.get("max_concurrency", 1)),
            max_duration_seconds=float(d.get("max_duration_seconds", 0)),
            max_retries=int(d.get("max_retries", 3)),
        )

    def to_dict(self) -> Dict:
        """Serializes this spec to a plain dict for envelope/storage."""
        return {
            "type": self.type,
            "python_version": self.python_version,
            "requirements": list(self.requirements),
            "image": self.image,
            "env_vars": dict(self.env_vars),
            "idle_ttl_seconds": self.idle_ttl_seconds,
            "max_invocations": self.max_invocations,
            "memory_limit_bytes": self.memory_limit_bytes,
            "cpu_limit": self.cpu_limit,
            "max_concurrency": self.max_concurrency,
            "max_duration_seconds": self.max_duration_seconds,
            "max_retries": self.max_retries,
        }
