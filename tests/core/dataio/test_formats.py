import builtins

import pytest

from axo_endpoint.core.dataio import get_format
from axo_endpoint.core.dataio.errors import IOFormatUnavailableError, UnknownIOFormatError


def test_raw_round_trip():
    fmt = get_format("raw").unwrap()
    assert fmt.decode(fmt.encode(b"hello")) == b"hello"


def test_raw_rejects_non_bytes():
    fmt = get_format("raw").unwrap()
    with pytest.raises(TypeError):
        fmt.encode("not bytes")


def test_pickle_round_trip():
    fmt = get_format("pickle").unwrap()
    obj = {"a": 1, "b": [1, 2, 3]}
    assert fmt.decode(fmt.encode(obj)) == obj


def test_csv_round_trip():
    import pandas as pd

    fmt = get_format("csv").unwrap()
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    result = fmt.decode(fmt.encode(df))
    pd.testing.assert_frame_equal(result, df)


def test_csv_decode_without_pandas_raises_clear_error(monkeypatch):
    # pandas is an optional extra now -- simulate it not being installed by
    # making the lazy `import pandas` inside _csv_decode fail, and confirm
    # that surfaces as a clear domain error rather than a raw ImportError.
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError("simulated missing pandas")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    fmt = get_format("csv").unwrap()
    with pytest.raises(IOFormatUnavailableError):
        fmt.decode(b"a,b\n1,2\n")


def test_npy_round_trip():
    import numpy as np

    fmt = get_format("npy").unwrap()
    arr = np.array([1, 2, 3])
    result = fmt.decode(fmt.encode(arr))
    assert (result == arr).all()


def test_unknown_format_returns_err():
    result = get_format("parquet")
    assert result.is_err
    assert isinstance(result.unwrap_err(), UnknownIOFormatError)
