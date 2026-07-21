from __future__ import annotations

from axo_endpoint.core.dataio.protocol import KEY_TYPES
from axo_endpoint.core.storage.backend import Key


def chunk_key(kind: str, name: str, version: int, index: int) -> Key:
    """Builds the key one chunk of registered data lives under, via whichever
    Key type ``kind``'s storage backend uses -- the one place this naming
    scheme is defined."""
    key_type = KEY_TYPES[kind]
    return key_type.from_str(f"{name}/{version}/chunk_{index:08d}")


def total_chunks_for(total_size: int, chunk_bytes: int) -> int:
    """Ceil-divides total_size by chunk_bytes. A zero-byte object needs zero chunks."""
    if total_size <= 0:
        return 0
    return -(-total_size // chunk_bytes)


def expected_chunk_len(total_size: int, chunk_bytes: int, index: int) -> int:
    """The number of bytes chunk ``index`` should carry -- chunk_bytes for
    every chunk except the last, which carries whatever remainder is left."""
    last_index = total_chunks_for(total_size, chunk_bytes) - 1
    if index == last_index:
        return total_size - index * chunk_bytes
    return chunk_bytes
