from axo_endpoint.service.container.handle import sanitize_container_name

LONG_FUNCTION_ID = "c29c6ec4c5ac051f360f38c173112238335be87b59f097d7b521bad448d3a487"


def test_sanitize_container_name_short_id_matches_previous_behavior():
    assert sanitize_container_name("my-func", 1) == "fn-my-func-v1"
    assert sanitize_container_name("my-func", 1, pool_index=2) == "fn-my-func-v1-p2"


def test_sanitize_container_name_long_id_keeps_version_suffix():
    name = sanitize_container_name(LONG_FUNCTION_ID, 1)
    assert name.endswith("-v1")
    assert len(name) <= 63


def test_sanitize_container_name_long_id_distinguishes_versions():
    v1 = sanitize_container_name(LONG_FUNCTION_ID, 1)
    v2 = sanitize_container_name(LONG_FUNCTION_ID, 2)
    assert v1 != v2
    assert v1.endswith("-v1")
    assert v2.endswith("-v2")


def test_sanitize_container_name_long_id_distinguishes_pool_members():
    p1 = sanitize_container_name(LONG_FUNCTION_ID, 1, pool_index=1)
    p2 = sanitize_container_name(LONG_FUNCTION_ID, 1, pool_index=2)
    p3 = sanitize_container_name(LONG_FUNCTION_ID, 1, pool_index=3)
    names = {p1, p2, p3}
    assert len(names) == 3
    assert p1.endswith("-v1-p1")
    assert p2.endswith("-v1-p2")
    assert p3.endswith("-v1-p3")
    for name in names:
        assert len(name) <= 63


def test_sanitize_container_name_never_exceeds_docker_limit():
    for pool_index in range(0, 6):
        for version in (1, 10, 100):
            name = sanitize_container_name(LONG_FUNCTION_ID, version, pool_index=pool_index)
            assert len(name) <= 63
