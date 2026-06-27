import json
import math
import asyncio
import math
import heapq
import json
from collections import deque,Counter
from typing import Optional, List, Dict, Any, Union


Number = Union[int, float]

class Metric:
    """
    A metric 'cell' that gathers numbers and computes stats.

    Modes:
      - limit == -1 (unbounded): streaming stats (Welford for mean/std, two-heaps for median).
      - limit > 0  (windowed): accumulate up to `limit`, then return snapshot and auto-reset.

    Methods:
      - add(x): record a value; returns snapshot dict if a window rolled (windowed mode), else None.
      - snapshot(): current stats (does not reset).
      - reset(): clear current state.
      - to_json(): JSON-serialized snapshot.

    Stats reported:
      - count, mean, median, std (sample), min, max
    """

    def __init__(self, name: str, limit: int = -1) -> None:
        if limit == 0 or limit < -1:
            raise ValueError("limit must be -1 (unbounded) or a positive integer")

        self.name = name
        self.limit = limit

        # Common aggregates
        self._count = 0
        self._min = math.inf
        self._max = -math.inf

        # --- Unbounded mode structures ---
        # Welford accumulators
        self._mean = 0.0
        self._M2 = 0.0
        # Two-heaps for streaming median
        # max-heap for lower half (store negatives), min-heap for upper half
        self._lo: List[float] = []  # max-heap via negatives
        self._hi: List[float] = []  # min-heap

        # --- Windowed mode structures ---
        self._buf: deque[float] = deque()
        self._buf_sum = 0.0

    # ---------------------------
    # Public API
    # ---------------------------
    def add_many(self,xs:List[Number])->Optional[Dict[str,Any]]:
        ys = []
        for x in xs:
            ys.append(self.add(x))

        return ys[-1] if len(ys) >0 else None

    def add(self, x: Number) -> Optional[Dict[str, Any]]:
        """Add one observation. Returns snapshot dict if window rolls over (windowed mode)."""
        val = float(x)

        if self.limit == -1:
            # Unbounded streaming
            self._update_common(val)
            self._welford_update(val)
            self._median_heaps_add(val)
            return None
        else:
            # Windowed
            self._buf.append(val)
            self._buf_sum += val
            self._update_common(val)

            if len(self._buf) >= self.limit:
                snap = self._compute_window_snapshot()
                self.reset()  # auto-reset after emitting window snapshot
                return snap
            return None

    def snapshot(self) -> Dict[str, Any]:
        """Return current stats without resetting."""
        if self._count == 0:
            return self._empty_snapshot()

        if self.limit == -1:
            # Streaming snapshot
            mean = self._mean
            std = math.sqrt(self._M2 / (self._count - 1)) if self._count > 1 else 0.0
            median = self._median_heaps_current()
        else:
            # Windowed snapshot (partial window)
            n = len(self._buf)
            if n == 0:
                return self._empty_snapshot()
            mean = self._buf_sum / n
            median = _median_of_sorted(sorted(self._buf))
            std = _sample_std_from_values(list(self._buf), mean)

        return {
            "name": self.name,
            "count": self._count if self.limit == -1 else len(self._buf),
            "mean": mean,
            "median": median,
            "std": std,
            "min": self._min,
            "max": self._max,
        }

    def to_json(self) -> str:
        """JSON-serialized snapshot."""
        return json.dumps(self.snapshot(), separators=(",", ":"), ensure_ascii=False)

    def reset(self) -> None:
        """Reset the metric cell."""
        self._count = 0
        self._min = math.inf
        self._max = -math.inf

        # Unbounded
        self._mean = 0.0
        self._M2 = 0.0
        self._lo.clear()
        self._hi.clear()

        # Windowed
        self._buf.clear()
        self._buf_sum = 0.0

    # ---------------------------
    # Internal helpers
    # ---------------------------
    def _update_common(self, val: float) -> None:
        self._count += 1
        if val < self._min:
            self._min = val
        if val > self._max:
            self._max = val

    # ---- Welford for streaming mean/std (unbounded) ----
    def _welford_update(self, x: float) -> None:
        n1 = self._count - 1
        if n1 < 0:
            # shouldn't happen; _count is incremented before calling this
            return
        delta = x - self._mean
        self._mean += delta / self._count
        delta2 = x - self._mean
        if self._count > 1:
            self._M2 += delta * delta2

    # ---- Two-heaps for streaming median (unbounded) ----
    def _median_heaps_add(self, x: float) -> None:
        if not self._lo or x <= -self._lo[0]:
            heapq.heappush(self._lo, -x)  # max-heap via negative
        else:
            heapq.heappush(self._hi, x)
        # Rebalance
        if len(self._lo) > len(self._hi) + 1:
            heapq.heappush(self._hi, -heapq.heappop(self._lo))
        elif len(self._hi) > len(self._lo):
            heapq.heappush(self._lo, -heapq.heappop(self._hi))

    def _median_heaps_current(self) -> float:
        if not self._lo and not self._hi:
            return 0.0
        if len(self._lo) == len(self._hi):
            return (-self._lo[0] + self._hi[0]) / 2.0
        else:
            return -self._lo[0]

    # ---- Windowed snapshot ----
    def _compute_window_snapshot(self) -> Dict[str, Any]:
        n = len(self._buf)
        values = list(self._buf)
        mean = self._buf_sum / n
        median = _median_of_sorted(sorted(values))
        std = _sample_std_from_values(values, mean)

        return {
            "name": self.name,
            "count": n,
            "mean": mean,
            "median": median,
            "std": std,
            "min": min(values),
            "max": max(values),
            "rolled": True,  # indicates window rollover
        }

    def _empty_snapshot(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
        }


# ---------- small math utilities ----------
def _median_of_sorted(sorted_vals: List[float]) -> float:
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_vals[mid])
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def _sample_std_from_values(vals: List[float], mean: Optional[float] = None) -> float:
    n = len(vals)
    if n <= 1:
        return 0.0
    if mean is None:
        mean = sum(vals) / n
    ssd = sum((v - mean) ** 2 for v in vals)
    return math.sqrt(ssd / (n - 1))



class MetricCollector:
    """
    Keeps a registry of Metric cells keyed by name.
    Async-safe (single asyncio.Lock).

    Core ops:
      - ensure(name, limit)            -> Metric
      - add(name, value)               -> Optional[dict]   (window snapshot on roll)
      - snapshot(name=None)            -> dict
      - to_json(name=None)             -> str
      - reset(name=None)               -> None
      - set_limit(name, limit)         -> None
      - get(name)                      -> Optional[Metric]
    """

    def __init__(self, default_limit: int = -1) -> None:
        if default_limit == 0 or default_limit < -1:
            raise ValueError("default_limit must be -1 or a positive integer")
        self._default_limit = default_limit
        self._lock = asyncio.Lock()
        self._metrics: Dict[str, Metric] = {}

    # -------------------
    # Registry management
    # -------------------
    async def ensure(self, name: str, *, limit: Optional[int] = None) -> Metric:
        """Get or create a Metric under 'name' (with optional limit)."""
        async with self._lock:
            m = self._metrics.get(name)
            if m is None:
                m = Metric(name=name, limit=self._default_limit if limit is None else limit)
                self._metrics[name] = m
            return m

    async def get(self, name: str) -> Optional[Metric]:
        async with self._lock:
            return self._metrics.get(name)

    async def set_limit(self, name: str, limit: int) -> None:
        """Update limit for an existing metric (resets current state)."""
        if limit == 0 or limit < -1:
            raise ValueError("limit must be -1 or a positive integer")
        async with self._lock:
            m = self._metrics.get(name)
            if m is None:
                m = Metric(name=name, limit=limit)
                self._metrics[name] = m
            else:
                # recreate to apply new limit and reset
                self._metrics[name] = Metric(name=name, limit=limit)

    # -------------------
    # Recording & reading
    # -------------------
    async def add(self, name: str, value: Number) -> Optional[Dict[str, Any]]:
        """
        Add one observation to the named metric.
        Returns a snapshot ONLY when that metric rolls over (finite-window mode).
        """
        m = await self.ensure(name)
        # Metric.add is sync; lock not needed per cell unless you want per-metric locks.
        return m.add(value)

    async def snapshot(self, name: Optional[str] = None) -> Dict[str, Any]:
        """
        Snapshot for a single metric (if name provided) or all metrics.
        Returns: dict[name] -> snapshot
        """
        async with self._lock:
            if name is not None:
                m = self._metrics.get(name)
                return {name: (m.snapshot() if m else _empty_named_snapshot(name))}
            # All
            return {n: m.snapshot() for n, m in self._metrics.items()}

    async def to_json(self, name: Optional[str] = None) -> str:
        """JSON-serialized snapshot (single metric or all)."""
        snap = await self.snapshot(name)
        return json.dumps(snap, separators=(",", ":"), ensure_ascii=False)

    async def reset(self, name: Optional[str] = None) -> None:
        """Reset one metric or all metrics."""
        async with self._lock:
            if name is not None:
                if name in self._metrics:
                    self._metrics[name].reset()
                return
            # reset all
            for m in self._metrics.values():
                m.reset()


def _empty_named_snapshot(name: str) -> Dict[str, Any]:
    return {
        name: {
            "name": name,
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
        }
    }