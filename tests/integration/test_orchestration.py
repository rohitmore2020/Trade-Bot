"""
Integration tests for TradingEngine lifecycle, wiring, and telemetry.
"""

from trade_bot.config.settings import AppConfig, ExecutionMode
from trade_bot.domain.models import Tick
from trade_bot.orchestration.factory import TradingEngineFactory


def test_trading_engine_backtest_lifecycle() -> None:
    config = AppConfig()
    config.system.mode = ExecutionMode.BACKTEST

    engine = TradingEngineFactory.build_engine(config)
    assert engine.is_running is False

    symbols = ["RELIANCE", "TCS"]
    engine.start(symbols)
    assert engine.is_running is True

    # Send a tick into the engine
    from datetime import datetime, timezone
    sample_tick = Tick(
        symbol="RELIANCE",
        timestamp=datetime.now(timezone.utc),
        last_price=2500.0,
        volume=10,
    )
    engine.on_tick(sample_tick)

    # Verify telemetry recorded tick
    metrics = engine.metrics.get_metrics()
    assert metrics.total_ticks_processed == 1

    engine.stop()
    assert engine.is_running is False
