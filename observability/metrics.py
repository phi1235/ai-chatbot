from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock


@dataclass(slots=True)
class MetricsRegistry:
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latencies_ms: list[float] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)

    def increment(self, name: str, value: int = 1) -> None:
        with self.lock:
            self.counters[name] += value

    def observe_latency(self, latency_ms: float) -> None:
        with self.lock:
            self.latencies_ms.append(latency_ms)
            if len(self.latencies_ms) > 1000:
                self.latencies_ms = self.latencies_ms[-1000:]

    def snapshot(self) -> dict[str, float | int | dict[str, int]]:
        with self.lock:
            count = len(self.latencies_ms)
            avg_latency = sum(self.latencies_ms) / count if count else 0.0
            return {
                "counters": dict(self.counters),
                "latency_count": count,
                "latency_avg_ms": round(avg_latency, 2),
                "latency_max_ms": round(max(self.latencies_ms), 2) if count else 0.0,
            }


metrics_registry = MetricsRegistry()
