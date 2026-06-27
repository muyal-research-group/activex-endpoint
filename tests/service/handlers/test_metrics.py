from axo_endpoint.core.network import Command
from axo_endpoint.service.handlers import MetricsHandler


def test_returns_metrics_provider_snapshot():
    handler = MetricsHandler(metrics_provider=lambda: {"queue_depth": 3, "submitted": 10})
    result = handler.handle(Command(operation="METRICS", content_type="application/json", envelope={}))

    assert result.ok is True
    assert result.metadata == {"queue_depth": 3, "submitted": 10}
