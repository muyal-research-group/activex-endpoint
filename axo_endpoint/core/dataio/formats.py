from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from option import Err, Ok, Result

from axo_endpoint.core.dataio.errors import DataIOError, IOFormatUnavailableError, UnknownIOFormatError


@dataclass(frozen=True)
class Format:
    """One (de)serializer pair, applied client-side around raw dataio bytes."""

    encode: Callable[[Any], bytes]
    decode: Callable[[bytes], Any]


def _raw_encode(obj: Any) -> bytes:
    if not isinstance(obj, (bytes, bytearray)):
        raise TypeError(f"format 'raw' requires bytes/bytearray, got {type(obj).__name__}")
    return bytes(obj)


def _raw_decode(data: bytes) -> bytes:
    return data


def _pickle_encode(obj: Any) -> bytes:
    import cloudpickle
    return cloudpickle.dumps(obj)


def _pickle_decode(data: bytes) -> Any:
    import cloudpickle
    return cloudpickle.loads(data)


def _csv_encode(obj: Any) -> bytes:
    return obj.to_csv(index=False).encode("utf-8")


def _csv_decode(data: bytes) -> Any:
    import io
    try:
        import pandas as pd
    except ImportError as exc:
        raise IOFormatUnavailableError(
            "format 'csv' requires the optional pandas extra -- "
            "install via `pip install axo_endpoint[pandas]`",
            context={"format": "csv"},
        ) from exc
    return pd.read_csv(io.BytesIO(data))


def _npy_encode(obj: Any) -> bytes:
    import io
    import numpy as np
    buf = io.BytesIO()
    np.save(buf, obj)
    return buf.getvalue()


def _npy_decode(data: bytes) -> Any:
    import io
    import numpy as np
    return np.load(io.BytesIO(data))


FORMATS: Dict[str, Format] = {
    "raw":    Format(_raw_encode, _raw_decode),
    "pickle": Format(_pickle_encode, _pickle_decode),
    "csv":    Format(_csv_encode, _csv_decode),
    "npy":    Format(_npy_encode, _npy_decode),
}


def get_format(name: str) -> Result[Format, DataIOError]:
    fmt = FORMATS.get(name)
    if fmt is None:
        return Err(UnknownIOFormatError(f"unknown io format {name!r}", context={"format": name}))
    return Ok(fmt)
