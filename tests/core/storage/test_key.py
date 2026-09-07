from axo_endpoint.core.storage import FsKey, StorageKey


def test_storage_key_round_trips_id_only():
    key = StorageKey(id="k1")
    assert StorageKey.from_str(key.to_str()) == key


def test_storage_key_round_trips_id_and_version():
    key = StorageKey(id="k1", version=3)
    assert StorageKey.from_str(key.to_str()) == key


def test_storage_key_round_trips_id_version_and_alias():
    key = StorageKey(id="k1", version=3, alias="alpha")
    assert StorageKey.from_str(key.to_str()) == key


def test_fs_key_round_trips_identity():
    key = FsKey(path="nested/dir/file.bin")
    assert FsKey.from_str(key.to_str()) == key
    assert key.to_str() == "nested/dir/file.bin"
