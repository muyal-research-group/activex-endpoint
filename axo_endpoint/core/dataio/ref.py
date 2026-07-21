from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class IORef:
    """Points at one blob a function can read or write via the dataio channel.

    ``kind`` selects which blob backend resolves it (only "fs" exists today).
    ``format`` selects the (de)serializer applied client-side, after the raw
    bytes have crossed the wire -- the endpoint only ever moves raw bytes.
    ``chunk_index`` is only meaningful for the "read_chunk" op (chunk-by-chunk
    reads of registered data) -- None for every other op, including ordinary
    whole-blob read/write.
    """

    kind: str
    location: str
    format: str = "raw"
    chunk_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind, "location": self.location, "format": self.format,
            "chunk_index": self.chunk_index,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "IORef":
        return IORef(
            kind=d["kind"], location=d["location"], format=d.get("format", "raw"),
            chunk_index=d.get("chunk_index"),
        )
