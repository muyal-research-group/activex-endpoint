from axo_endpoint.core.data.chunking import chunk_key, expected_chunk_len, total_chunks_for
from axo_endpoint.core.storage import FsKey


def test_chunk_key_builds_fs_key_for_fs_kind():
    key = chunk_key("fs", "df1", 1, 3)
    assert key == FsKey(path="df1/1/chunk_00000003")


def test_total_chunks_for_exact_multiple():
    assert total_chunks_for(20, 10) == 2


def test_total_chunks_for_remainder_rounds_up():
    assert total_chunks_for(25, 10) == 3


def test_total_chunks_for_zero_size_is_zero_chunks():
    assert total_chunks_for(0, 10) == 0


def test_expected_chunk_len_full_chunks():
    assert expected_chunk_len(25, 10, 0) == 10
    assert expected_chunk_len(25, 10, 1) == 10


def test_expected_chunk_len_last_chunk_is_remainder():
    assert expected_chunk_len(25, 10, 2) == 5


def test_expected_chunk_len_exact_multiple_last_chunk_full():
    assert expected_chunk_len(20, 10, 1) == 10
