from axo_shared.runtime.spec import RuntimeSpec


def test_defaults():
    spec = RuntimeSpec()
    assert spec.type == "process"
    assert spec.python_version == "3.11"
    assert spec.requirements == []
    assert spec.image is None
    assert spec.env_vars == {}
    assert spec.idle_ttl_seconds == 300.0
    assert spec.max_invocations == 0
    assert spec.memory_limit_bytes is None
    assert spec.cpu_limit is None
    assert spec.max_concurrency == 1
    assert spec.max_duration_seconds == 0
    assert spec.max_retries == 3


def test_to_dict_round_trips_through_from_dict():
    spec = RuntimeSpec(
        type="container",
        python_version="3.10",
        requirements=["pandas"],
        image="axo-runner:3.10",
        env_vars={"FOO": "bar"},
        idle_ttl_seconds=60.0,
        max_invocations=5,
        memory_limit_bytes=536870912,
        cpu_limit=0.5,
        max_concurrency=4,
        max_duration_seconds=120.0,
        max_retries=5,
    )
    assert RuntimeSpec.from_dict(spec.to_dict()) == spec


def test_from_dict_fills_in_defaults_for_missing_keys():
    spec = RuntimeSpec.from_dict({})
    assert spec == RuntimeSpec()


def test_from_dict_partial_overrides_only_given_keys():
    spec = RuntimeSpec.from_dict({"type": "container", "python_version": "3.10"})
    assert spec.type == "container"
    assert spec.python_version == "3.10"
    assert spec.requirements == []
    assert spec.idle_ttl_seconds == 300.0
