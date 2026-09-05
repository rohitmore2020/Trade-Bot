"""
Unit tests for Candle Aggregator.
"""

from datetime import datetime, timezone
from typing import List
from trade_bot.data.aggregator import TimeframeCandleAggregator
from trade_bot.domain.models import Candle, Tick


def test_candle_aggregation_closes_on_interval_boundary() -> None:
    aggregator = TimeframeCandleAggregator(timeframe_seconds=60)
    closed_candles: List[Candle] = []
    aggregator.register_candle_handler(closed_candles.append)

    # Tick 1: 09:15:10 @ 2500, vol 10
    t1 = Tick(
        symbol="RELIANCE",
        timestamp=datetime(2026, 9, 5, 9, 15, 10, tzinfo=timezone.utc),
        last_price=2500.0,
        volume=10,
    )
    aggregator.process_tick(t1)
    assert len(closed_candles) == 0

    # Tick 2: 09:15:30 @ 2520, vol 20
    t2 = Tick(
        symbol="RELIANCE",
        timestamp=datetime(2026, 9, 5, 9, 15, 30, tzinfo=timezone.utc),
        last_price=2520.0,
        volume=20,
    )
    aggregator.process_tick(t2)
    assert len(closed_candles) == 0

    # Tick 3: 09:16:05 @ 2510, vol 15 -> crosses 60s boundary, emits 09:15 candle
    t3 = Tick(
        symbol="RELIANCE",
        timestamp=datetime(2026, 9, 5, 9, 16, 5, tzinfo=timezone.utc),
        last_price=2510.0,
        volume=15,
    )
    closed = aggregator.process_tick(t3)
    assert closed is not None
    assert len(closed_candles) == 1

    bar = closed_candles[0]
    assert bar.symbol == "RELIANCE"
    assert bar.open == 2500.0
    assert bar.high == 2520.0
    assert bar.low == 2500.0
    assert bar.close == 2520.0
    assert bar.volume == 30
    assert bar.is_closed is True
