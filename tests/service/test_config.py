from axo_endpoint.service.config import Config


def test_defaults_with_no_env_vars(clean_endpoint_env):
    config = Config()

    assert config.AXO_ENDPOINT_ID == "axo-endpoint-0"
    assert config.AXO_ENDPOINT_ROUTER_BIND == "tcp://0.0.0.0:5555"
    assert config.AXO_ENDPOINT_PUB_BIND == "tcp://0.0.0.0:5556"
    assert config.AXO_ENDPOINT_SUB_CONNECT == []
    assert config.AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS == 5.0
    assert config.AXO_ENDPOINT_HEARTBEAT_TTL_SECONDS == 30.0
    assert config.AXO_ENDPOINT_QUEUE_MAX_DEPTH == 1000
    assert config.AXO_ENDPOINT_QUEUE_WORKERS == 4
    assert config.AXO_ENDPOINT_WORKER_IDLE_TTL_SECONDS == 300.0
    assert config.AXO_ENDPOINT_WORKER_GC_INTERVAL_SECONDS == 30.0
    assert config.AXO_ENDPOINT_WORKER_MAX_INVOCATIONS == 0
    assert config.AXO_ENDPOINT_WORKER_RLIMIT_AS_BYTES == 512 * 1024 * 1024
    assert config.AXO_ENDPOINT_WORKER_RLIMIT_CPU_SECONDS == 30
    assert config.AXO_ENDPOINT_SCRATCH_ROOT == "/tmp/axo_endpoint/scratch"
    assert config.AXO_ENDPOINT_SCRATCH_GC_INTERVAL_SECONDS == 60.0


def test_env_var_overrides_with_correct_type_coercion(clean_endpoint_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_ID", "axo-endpoint-7")
    monkeypatch.setenv("AXO_ENDPOINT_QUEUE_MAX_DEPTH", "50")
    monkeypatch.setenv("AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("AXO_ENDPOINT_WORKER_MAX_INVOCATIONS", "100")

    config = Config()

    assert config.AXO_ENDPOINT_ID == "axo-endpoint-7"
    assert config.AXO_ENDPOINT_QUEUE_MAX_DEPTH == 50
    assert isinstance(config.AXO_ENDPOINT_QUEUE_MAX_DEPTH, int)
    assert config.AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS == 2.5
    assert isinstance(config.AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS, float)
    assert config.AXO_ENDPOINT_WORKER_MAX_INVOCATIONS == 100


def test_sub_connect_splits_comma_separated_list(clean_endpoint_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_SUB_CONNECT", "tcp://a:1,tcp://b:2,tcp://c:3")
    config = Config()
    assert config.AXO_ENDPOINT_SUB_CONNECT == ["tcp://a:1", "tcp://b:2", "tcp://c:3"]


def test_update_overrides_existing_field(clean_endpoint_env):
    config = Config()
    config.update(AXO_ENDPOINT_QUEUE_MAX_DEPTH=5)
    assert config.AXO_ENDPOINT_QUEUE_MAX_DEPTH == 5


def test_update_is_a_noop_for_unknown_keys(clean_endpoint_env):
    config = Config()
    config.update(NOT_A_REAL_FIELD=123)
    assert not hasattr(config, "NOT_A_REAL_FIELD")
