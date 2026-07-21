from axo_vem.config import Config


def test_defaults_with_no_env_vars(monkeypatch):
    for name in (
        "AXO_VEM_ROUTER_BIND",
        "AXO_VEM_HTTP_HOST",
        "AXO_VEM_HTTP_PORT",
        "AXO_VEM_KURRENT_URI",
        "AXO_VEM_MONGO_URI",
        "AXO_VEM_MONGO_DB_NAME",
        "AXO_VEM_XOLO_URI",
        "AXO_VEM_XOLO_API_KEY",
        "AXO_VEM_XOLO_ACCOUNT_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    config = Config()

    assert config.AXO_VEM_ROUTER_BIND == "tcp://0.0.0.0:6000"
    assert config.AXO_VEM_HTTP_HOST == "0.0.0.0"
    assert config.AXO_VEM_HTTP_PORT == 8080
    assert config.AXO_VEM_KURRENT_URI == "esdb://localhost:2113?tls=false"
    assert config.AXO_VEM_MONGO_URI == "mongodb://localhost:27017"
    assert config.AXO_VEM_MONGO_DB_NAME == "axo_vem"
    assert config.AXO_VEM_XOLO_URI == "http://localhost:10000/api/v4"
    assert config.AXO_VEM_XOLO_API_KEY == ""
    assert config.AXO_VEM_XOLO_ACCOUNT_ID == ""


def test_env_var_overrides(monkeypatch):
    monkeypatch.setenv("AXO_VEM_ROUTER_BIND", "tcp://0.0.0.0:7000")
    monkeypatch.setenv("AXO_VEM_HTTP_PORT", "9090")

    config = Config()

    assert config.AXO_VEM_ROUTER_BIND == "tcp://0.0.0.0:7000"
    assert config.AXO_VEM_HTTP_PORT == 9090
    assert isinstance(config.AXO_VEM_HTTP_PORT, int)


def test_update_overrides_existing_field():
    config = Config()
    config.update(AXO_VEM_HTTP_PORT=1234)
    assert config.AXO_VEM_HTTP_PORT == 1234


def test_update_is_a_noop_for_unknown_keys():
    config = Config()
    config.update(NOT_A_REAL_FIELD=123)
    assert not hasattr(config, "NOT_A_REAL_FIELD")
