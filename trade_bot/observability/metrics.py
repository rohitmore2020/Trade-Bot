"""
Operational and Trading Metrics Collector.

Tracks order latencies, execution statistics, fill rates, and error counters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Dict


@dataclass
class PerformanceMetrics:
    """Snapshot of platform operational counters."""
    total_ticks_processed: int = 0
    total_candles_closed: int = 0
    total_signals_emitted: int = 0
    total_orders_submitted: int = 0
    total_orders_filled: int = 0
    total_orders_rejected: int = 0
    total_risk_violations: int = 0


class MetricsCollector:
    """Thread-safe operational telemetry counters."""

    def __init__(self) -> None:
        self._metrics = PerformanceMetrics()
        self._lock = threading.Lock()

    def record_tick(self) -> None:
        with self._lock:
            self._metrics.total_ticks_processed += 1

    def record_candle(self) -> None:
        with self._lock:
            self._metrics.total_candles_closed += 1

    def record_signal(self) -> None:
        with self._lock:
            self._metrics.total_signals_emitted += 1

    def record_order_submitted(self) -> None:
        with self._lock:
            self._metrics.total_orders_submitted += 1

    def record_order_filled(self) -> None:
        with self._lock:
            self._metrics.total_orders_filled += 1

    def record_order_rejected(self) -> None:
        with self._lock:
            self._metrics.total_orders_rejected += 1

    def record_risk_violation(self) -> None:
        with self._lock:
            self._metrics.total_risk_violations += 1

    def get_metrics(self) -> PerformanceMetrics:
        with self._lock:
            return PerformanceMetrics(
                total_ticks_processed=self._metrics.total_ticks_processed,
                total_candles_closed=self._metrics.total_candles_closed,
                total_signals_emitted=self._metrics.total_signals_emitted,
                total_orders_submitted=self._metrics.total_orders_submitted,
                total_orders_filled=self._metrics.total_orders_filled,
                total_orders_rejected=self._metrics.total_orders_rejected,
                total_risk_violations=self._metrics.total_risk_violations,
            )
