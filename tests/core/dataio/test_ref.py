from axo_endpoint.core.dataio import IORef


def test_to_dict_from_dict_round_trip():
    ref = IORef(kind="fs", location="a/b.csv", format="csv")
    d = ref.to_dict()
    assert d == {"kind": "fs", "location": "a/b.csv", "format": "csv", "chunk_index": None}
    assert IORef.from_dict(d) == ref


def test_from_dict_defaults_format_to_raw():
    ref = IORef.from_dict({"kind": "fs", "location": "x"})
    assert ref.format == "raw"


def test_chunk_index_round_trips():
    ref = IORef(kind="fs", location="a/1", format="raw", chunk_index=3)
    d = ref.to_dict()
    assert d["chunk_index"] == 3
    assert IORef.from_dict(d) == ref
