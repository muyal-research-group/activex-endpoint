# tests/test_metrics.py
# Reference only — tests axo_endpoint/old/ code, not maintained against new code.
import json
import math
import pytest

# Adjust this import to where you placed the classes
from axo_endpoint.metrics import Metric, MetricCollector


# -----------------------------
# Metric (unbounded / streaming)
# -----------------------------
def test_metric_streaming_basic_stats():
    m = Metric(name="latency_ms", limit=-1)
    for x in [1.0, 2.0, 3.0, 4.0]:
        m.add(x)

    snap = m.snapshot()
    assert snap["name"] == "latency_ms"
    assert snap["count"] == 4
    assert snap["min"] == 1.0
    assert snap["max"] == 4.0
    assert snap["mean"] == pytest.approx(2.5, rel=1e-9)
    assert snap["median"] == pytest.approx(2.5, rel=1e-9)

    # sample std for [1,2,3,4] is sqrt(5/3)
    expected_std = math.sqrt(5.0 / 3.0)
    assert snap["std"] == pytest.approx(expected_std, rel=1e-9)


def test_metric_streaming_json_snapshot():
    m = Metric("st", limit=-1)
    for x in [10, 20, 30]:
        m.add(x)
    s = m.to_json()
    data = json.loads(s)
    assert data["name"] == "st"
    assert data["count"] == 3
    assert data["mean"] == pytest.approx(20.0, rel=1e-9)
    assert data["median"] == pytest.approx(20.0, rel=1e-9)


def test_metric_streaming_reset():
    m = Metric("r", limit=-1)
    for x in [5, 7]:
        m.add(x)
    m.reset()
    snap = m.snapshot()
    assert snap["count"] == 0
    assert snap["mean"] == 0.0
    assert snap["median"] == 0.0
    assert snap["std"] == 0.0
    assert snap["min"] == 0.0
    assert snap["max"] == 0.0


# -------------------------
# Metric (windowed / limit)
# -------------------------
def test_metric_window_rollover_and_reset():
    m = Metric("win", limit=3)
    # first two values: no rollover yet
    assert m.add(10.0) is None
    assert m.add(20.0) is None
    # third value triggers rollover -> returns snapshot
    snap = m.add(30.0)
    assert isinstance(snap, dict)
    assert snap["name"] == "win"
    assert snap["rolled"] is True
    assert snap["count"] == 3
    assert snap["mean"] == pytest.approx(20.0, rel=1e-9)
    assert snap["median"] == pytest.approx(20.0, rel=1e-9)
    # sample std of [10,20,30] = 10
    assert snap["std"] == pytest.approx(10.0, rel=1e-9)
    assert snap["min"] == 10.0
    assert snap["max"] == 30.0

    # After rollover, metric auto-reset
    post = m.snapshot()
    assert post["count"] == 0
    assert post["mean"] == 0.0


def test_metric_window_partial_snapshot_no_roll():
    m = Metric("win2", limit=4)
    for x in [1, 2]:
        assert m.add(x) is None
    snap = m.snapshot()
    assert snap["count"] == 2
    assert snap["mean"] == pytest.approx(1.5, rel=1e-9)
    assert snap["median"] == pytest.approx(1.5, rel=1e-9)
    # sample std for [1,2] = sqrt((0.5^2 + 0.5^2)/(2-1)) = 0.707106...
    assert snap["std"] == pytest.approx(math.sqrt(0.5), rel=1e-9)


def test_metric_invalid_limit():
    with pytest.raises(ValueError):
        Metric("bad", limit=0)
    with pytest.raises(ValueError):
        Metric("bad2", limit=-2)


# -------------------
# MetricCollector API
# -------------------
@pytest.mark.asyncio
async def test_collector_add_and_snapshot_all():
    c = MetricCollector(default_limit=-1)  # streaming
    await c.add("service_time_ms", 12.0)
    await c.add("service_time_ms", 18.0)
    await c.add("ops_rate", 1.0)

    snap_all = await c.snapshot()
    assert "service_time_ms" in snap_all
    assert "ops_rate" in snap_all

    st = snap_all["service_time_ms"]
    assert st["count"] == 2
    assert st["mean"] == pytest.approx(15.0, rel=1e-9)
    assert st["median"] == pytest.approx(15.0, rel=1e-9)
    assert st["min"] == 12.0
    assert st["max"] == 18.0


@pytest.mark.asyncio
async def test_collector_to_json_single_and_all():
    c = MetricCollector()
    await c.add("x", 1.0)
    await c.add("x", 3.0)

    # single
    js1 = await c.to_json("x")
    d1 = json.loads(js1)
    assert "x" in d1
    assert d1["x"]["mean"] == pytest.approx(2.0, rel=1e-9)

    # all
    js_all = await c.to_json()
    d_all = json.loads(js_all)
    assert "x" in d_all


@pytest.mark.asyncio
async def test_collector_set_limit_and_rollover():
    c = MetricCollector(default_limit=-1)

    # Switch/create a windowed metric
    await c.set_limit("winlat", 3)
    # add two -> no roll
    rolled = await c.add("winlat", 10.0)
    assert rolled is None
    rolled = await c.add("winlat", 20.0)
    assert rolled is None
    # third -> roll and auto-reset
    rolled = await c.add("winlat", 30.0)
    assert isinstance(rolled, dict)
    assert rolled["count"] == 3
    assert rolled["mean"] == pytest.approx(20.0, rel=1e-9)

    # After reset, count must be 0
    snap = await c.snapshot("winlat")
    assert snap["winlat"]["count"] == 0


@pytest.mark.asyncio
async def test_collector_reset_specific_and_all():
    c = MetricCollector()
    await c.add("a", 1.0)
    await c.add("b", 5.0)

    await c.reset("a")
    snap = await c.snapshot()
    assert snap["a"]["count"] == 0
    assert snap["b"]["count"] == 1

    await c.reset()
    snap2 = await c.snapshot()
    assert snap2["a"]["count"] == 0
    assert snap2["b"]["count"] == 0


@pytest.mark.asyncio
async def test_collector_ensure_and_get():
    c = MetricCollector()
    m1 = await c.ensure("qps")
    assert m1 is not None
    m2 = await c.get("qps")
    assert m2 is m1

    # ensure with explicit limit
    m3 = await c.ensure("win", limit=5)
    assert m3 is not None
    assert m3.snapshot()["count"] == 0
