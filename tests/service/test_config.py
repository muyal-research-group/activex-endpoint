from axo_endpoint.config import Config


def test_defaults_with_no_env_vars(clean_env):
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
    assert config.AXO_ENDPOINT_CONSENSUS_BLOB_CHUNK_BYTES == 262144
    assert config.AXO_ENDPOINT_CONSENSUS_BLOB_RATE_LIMIT_BYTES_PER_SECOND == 1048576
    assert config.AXO_ENDPOINT_CONSENSUS_BLOB_TICK_INTERVAL_SECONDS == 0.1
    assert config.AXO_ENDPOINT_BLOB_REPLICATION_IDLE_SECONDS == 60.0
    assert config.AXO_ENDPOINT_BLOB_REPLICATION_ENABLED_KINDS == ["fs"]
    assert config.AXO_ENDPOINT_BLOB_REPLICATION_RECHECK_SECONDS == 300.0
    assert config.AXO_ENDPOINT_ACTIVITY_LOG_MAX_ENTRIES == 10000
    assert config.AXO_ENDPOINT_API_URI is None
    assert config.AXO_ENDPOINT_API_PUBLISH_TIMEOUT_MS == 1000
    assert config.AXO_ENDPOINT_CONTAINER_MEMORY_LIMIT_BYTES == 1024 * 1024 * 1024
    assert config.AXO_ENDPOINT_CONTAINER_CPU_LIMIT == 1.0


def test_api_uri_set_from_env(clean_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_API_URI", "tcp://axo-vem:6000")
    config = Config()
    assert config.AXO_ENDPOINT_API_URI == "tcp://axo-vem:6000"


def test_env_var_overrides_with_correct_type_coercion(clean_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_ID", "axo-endpoint-7")
    monkeypatch.setenv("AXO_ENDPOINT_QUEUE_MAX_DEPTH", "50")
    monkeypatch.setenv("AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("AXO_ENDPOINT_WORKER_MAX_INVOCATIONS", "100")
    monkeypatch.setenv("AXO_ENDPOINT_CONSENSUS_BLOB_CHUNK_BYTES", "1024")
    monkeypatch.setenv("AXO_ENDPOINT_CONSENSUS_BLOB_RATE_LIMIT_BYTES_PER_SECOND", "2048")
    monkeypatch.setenv("AXO_ENDPOINT_CONSENSUS_BLOB_TICK_INTERVAL_SECONDS", "0.5")
    monkeypatch.setenv("AXO_ENDPOINT_BLOB_REPLICATION_IDLE_SECONDS", "30")
    monkeypatch.setenv("AXO_ENDPOINT_BLOB_REPLICATION_ENABLED_KINDS", "fs,s3")
    monkeypatch.setenv("AXO_ENDPOINT_BLOB_REPLICATION_RECHECK_SECONDS", "120")
    monkeypatch.setenv("AXO_ENDPOINT_ACTIVITY_LOG_MAX_ENTRIES", "500")
    monkeypatch.setenv("AXO_ENDPOINT_CONTAINER_MEMORY_LIMIT_BYTES", "268435456")
    monkeypatch.setenv("AXO_ENDPOINT_CONTAINER_CPU_LIMIT", "0.5")

    config = Config()

    assert config.AXO_ENDPOINT_ID == "axo-endpoint-7"
    assert config.AXO_ENDPOINT_QUEUE_MAX_DEPTH == 50
    assert isinstance(config.AXO_ENDPOINT_QUEUE_MAX_DEPTH, int)
    assert config.AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS == 2.5
    assert isinstance(config.AXO_ENDPOINT_HEARTBEAT_INTERVAL_SECONDS, float)
    assert config.AXO_ENDPOINT_WORKER_MAX_INVOCATIONS == 100
    assert config.AXO_ENDPOINT_CONSENSUS_BLOB_CHUNK_BYTES == 1024
    assert config.AXO_ENDPOINT_CONSENSUS_BLOB_RATE_LIMIT_BYTES_PER_SECOND == 2048
    assert config.AXO_ENDPOINT_CONSENSUS_BLOB_TICK_INTERVAL_SECONDS == 0.5
    assert config.AXO_ENDPOINT_BLOB_REPLICATION_IDLE_SECONDS == 30.0
    assert config.AXO_ENDPOINT_BLOB_REPLICATION_ENABLED_KINDS == ["fs", "s3"]
    assert config.AXO_ENDPOINT_BLOB_REPLICATION_RECHECK_SECONDS == 120.0
    assert config.AXO_ENDPOINT_ACTIVITY_LOG_MAX_ENTRIES == 500
    assert config.AXO_ENDPOINT_CONTAINER_MEMORY_LIMIT_BYTES == 268435456
    assert config.AXO_ENDPOINT_CONTAINER_CPU_LIMIT == 0.5


def test_sub_connect_splits_comma_separated_list(clean_env, monkeypatch):
    monkeypatch.setenv("AXO_ENDPOINT_SUB_CONNECT", "tcp://a:1,tcp://b:2,tcp://c:3")
    config = Config()
    assert config.AXO_ENDPOINT_SUB_CONNECT == ["tcp://a:1", "tcp://b:2", "tcp://c:3"]


def test_update_overrides_existing_field(clean_env):
    config = Config()
    config.update(AXO_ENDPOINT_QUEUE_MAX_DEPTH=5)
    assert config.AXO_ENDPOINT_QUEUE_MAX_DEPTH == 5


def test_update_is_a_noop_for_unknown_keys(clean_env):
    config = Config()
    config.update(NOT_A_REAL_FIELD=123)
    assert not hasattr(config, "NOT_A_REAL_FIELD")
