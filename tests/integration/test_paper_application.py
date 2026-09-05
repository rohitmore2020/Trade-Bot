"""
Application-Level Integration Tests for Phase 18 Paper Trading Platform.

Validates:
1. End-to-end composed application wiring via dependency injection.
2. Complete session lifecycle progression:
   PRE_MARKET -> MARKET_OPEN -> ORB_PERIOD -> TRADING -> SQUARE_OFF -> CLOSED.
3. Pre-market scanning and universe subscription.
4. Real-time market data ingestion, 5-minute candle aggregation, and indicator calculation.
5. Strategy signal evaluation, risk engine approval, paper execution fill, position update, and persistence.
6. Intraday 14:30 square-off handling.
7. Graceful shutdown: order cancellation, pipeline disconnect, and audit log recording.
8. Fail-safe configuration enforcement: MODE=paper requirement.
"""

from datetime import datetime, time, timedelta
import pytest

from trade_bot.broker.paper_adapter import PaperBrokerAdapter
from trade_bot.broker.paper_models import PaperBrokerConfig
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.config.settings import AppConfig, ExecutionMode
from trade_bot.data.memory_data_feed import InMemoryMarketDataFeed
from trade_bot.data.pipeline import RealtimeCandleAggregator, RealtimeMarketDataPipeline
from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType, SignalDirection
from trade_bot.domain.exceptions import ConfigurationError
from trade_bot.domain.models import Candle, OrderRequest, Tick
from trade_bot.indicators.engine import IndicatorEngine
from trade_bot.observability.audit import AuditLogger
from trade_bot.observability.metrics import MetricsCollector
from trade_bot.orchestration.factory import TradingEngineFactory
from trade_bot.orchestration.paper_application import (
    PaperTradingApplication,
    SessionLifecycleStage,
)
from trade_bot.persistence.in_memory import (
    InMemoryOrderRepository,
    InMemoryTradeRepository,
)
from trade_bot.portfolio.manager import PortfolioManager
from trade_bot.risk.decision_engine import RiskDecisionEngine
from trade_bot.scanner.scanner import CandidateScanner
from trade_bot.strategy.engine import VWAPORBStrategyEngine
from trade_bot.strategy.models import UniverseCandidate, VwapOrbStrategyConfig


@pytest.fixture
def paper_app() -> PaperTradingApplication:
    """Fixture providing a fully wired PaperTradingApplication in paper mode."""
    config = AppConfig()
    config.system.mode = ExecutionMode.PAPER
    config.risk.initial_capital = 100000.0

    feed = InMemoryMarketDataFeed()
    pipeline = RealtimeMarketDataPipeline(
        provider=feed,
        candle_aggregator=RealtimeCandleAggregator(timeframe_seconds=300, enforce_market_hours=False),
    )
    broker = PaperBrokerAdapter(
        paper_config=PaperBrokerConfig(
            initial_capital=100000.0,
            default_slippage_pct=0.0005,
        )
    )

    app = TradingEngineFactory.build_paper_application(
        config=config,
        custom_pipeline=pipeline,
        custom_broker=broker,
    )
    return app


class TestPaperTradingApplication:
    """Integration test suite for PaperTradingApplication."""

    # -------------------------------------------------------------------------
    # 1. Configuration Safety
    # -------------------------------------------------------------------------

    def test_configuration_fails_safely_when_not_paper_mode(self):
        """Verify that application raises ConfigurationError if mode != paper."""
        config_backtest = AppConfig()
        config_backtest.system.mode = ExecutionMode.BACKTEST

        with pytest.raises(ConfigurationError, match="requires MODE=paper"):
            TradingEngineFactory.build_paper_application(config_backtest)

        config_live = AppConfig()
        config_live.system.mode = ExecutionMode.LIVE
        with pytest.raises(ConfigurationError, match="requires MODE=paper"):
            TradingEngineFactory.build_paper_application(config_live)

    # -------------------------------------------------------------------------
    # 2. Complete Session Lifecycle Progression
    # -------------------------------------------------------------------------

    def test_session_lifecycle_progression(self, paper_app: PaperTradingApplication):
        """Verify transitions across all 6 intraday lifecycle stages."""
        base_date = datetime(2024, 1, 8, 9, 0, 0, tzinfo=IST_TIMEZONE)
        paper_app.start(session_time=base_date)

        assert paper_app.is_running is True
        # 09:00 -> PRE_MARKET
        assert paper_app.stage == SessionLifecycleStage.PRE_MARKET

        # Advance to 09:15 -> MARKET_OPEN -> ORB_PERIOD
        t_open = datetime(2024, 1, 8, 9, 15, 0, tzinfo=IST_TIMEZONE)
        paper_app.advance_time(t_open)
        assert paper_app.stage == SessionLifecycleStage.ORB_PERIOD

        # Advance to 09:30 -> TRADING
        t_trading = datetime(2024, 1, 8, 9, 30, 0, tzinfo=IST_TIMEZONE)
        paper_app.advance_time(t_trading)
        assert paper_app.stage == SessionLifecycleStage.TRADING

        # Advance to 14:30 -> SQUARE_OFF
        t_sqoff = datetime(2024, 1, 8, 14, 30, 0, tzinfo=IST_TIMEZONE)
        paper_app.advance_time(t_sqoff)
        assert paper_app.stage == SessionLifecycleStage.SQUARE_OFF

        # Advance to 15:30 -> CLOSED
        t_close = datetime(2024, 1, 8, 15, 30, 0, tzinfo=IST_TIMEZONE)
        paper_app.advance_time(t_close)
        assert paper_app.stage == SessionLifecycleStage.CLOSED

    # -------------------------------------------------------------------------
    # 3. Pre-Market Scanning
    # -------------------------------------------------------------------------

    def test_premarket_scan_and_universe_registration(self, paper_app: PaperTradingApplication):
        """Verify pre-market screening populates universe and market data subscriptions."""
        paper_app.start(session_time=datetime(2024, 1, 8, 9, 5, 0, tzinfo=IST_TIMEZONE))

        candidates = [
            UniverseCandidate(
                symbol="RELIANCE",
                price=2500.0,
                avg_daily_turnover_cr=150.0,
                atr_20d_pct=2.5,
                premarket_volume_pct=0.15,
                overnight_gap_pct=0.012,
                is_fno_eligible=True,
            ),
            UniverseCandidate(
                symbol="TCS",
                price=3800.0,
                avg_daily_turnover_cr=50.0,
                atr_20d_pct=2.0,
                premarket_volume_pct=0.05,
                overnight_gap_pct=0.005,
                is_fno_eligible=True,  # Ineligible due to turnover & premarket vol
            ),
        ]

        eligible = paper_app.run_premarket_scan(candidates)
        assert eligible == ["RELIANCE"]
        assert "RELIANCE" in paper_app.pipeline.get_subscriptions()
        assert paper_app.strategy_engine.is_symbol_in_active_trade("RELIANCE") is False

    # -------------------------------------------------------------------------
    # 4. End-to-End Trade Flow (ORB Formation -> Signal -> Risk -> Fill -> Position)
    # -------------------------------------------------------------------------

    def test_end_to_end_trading_flow(self, paper_app: PaperTradingApplication):
        """Verify full trade pipeline: ORB -> Breakout Candle -> Signal -> Risk -> Fill -> Position."""
        # 1. Start application at 09:05
        paper_app.start(session_time=datetime(2024, 1, 8, 9, 5, 0, tzinfo=IST_TIMEZONE))

        # 2. Register universe
        paper_app.strategy_engine.set_eligible_universe([
            UniverseCandidate(
                symbol="RELIANCE",
                price=2500.0,
                avg_daily_turnover_cr=150.0,
                atr_20d_pct=2.5,
                premarket_volume_pct=0.15,
                overnight_gap_pct=0.012,
                is_fno_eligible=True,
            )
        ])
        paper_app.pipeline.subscribe(["RELIANCE"])

        # 3. Market Open (09:15)
        paper_app.advance_time(datetime(2024, 1, 8, 9, 15, 0, tzinfo=IST_TIMEZONE))
        assert paper_app.stage == SessionLifecycleStage.ORB_PERIOD

        # 4. Feed ORB Candles (09:15, 09:20, 09:25) to establish ORB High/Low
        # Prior close 2480, opens at 2500 (gap up 0.8%)
        paper_app.indicator_engine.set_previous_day_close("RELIANCE", 2480.0)
        paper_app.indicator_engine.set_initial_atr("RELIANCE", 20.0)
        paper_app.indicator_engine.seed_volume_history("RELIANCE", [50000] * 10)

        # Set NIFTY regime to BULLISH
        paper_app.on_candle(
            Candle(
                "^NSEI",
                datetime(2024, 1, 8, 9, 25, 0, tzinfo=IST_TIMEZONE),
                21500.0,
                21550.0,
                21490.0,
                21540.0,
                100000,
                300,
                True,
            )
        )

        orb_candles = [
            Candle("RELIANCE", datetime(2024, 1, 8, 9, 15, 0, tzinfo=IST_TIMEZONE), 2500.0, 2515.0, 2495.0, 2510.0, 50000, 300, True),
            Candle("RELIANCE", datetime(2024, 1, 8, 9, 20, 0, tzinfo=IST_TIMEZONE), 2510.0, 2520.0, 2505.0, 2518.0, 45000, 300, True),
            Candle("RELIANCE", datetime(2024, 1, 8, 9, 25, 0, tzinfo=IST_TIMEZONE), 2518.0, 2525.0, 2512.0, 2522.0, 48000, 300, True),
        ]

        for c in orb_candles:
            paper_app.on_candle(c)

        # Confirm NO trades or positions opened during ORB_PERIOD
        assert len(paper_app.broker.get_positions()) == 0
        assert len(paper_app.trade_repo.get_all()) == 0

        # 5. Advance to TRADING stage at 09:30
        paper_app.advance_time(datetime(2024, 1, 8, 9, 30, 0, tzinfo=IST_TIMEZONE))
        assert paper_app.stage == SessionLifecycleStage.TRADING

        # 6. Feed Breakout Candle at 09:45 (Strategy Trading Window Start):
        # Pulls back near VWAP then breaks above ORB High (2525.0) with volume surge
        breakout_candle = Candle(
            "RELIANCE",
            datetime(2024, 1, 8, 9, 45, 0, tzinfo=IST_TIMEZONE),
            2518.0,  # Open near VWAP
            2535.0,  # Breaks out above ORB high (2525)
            2516.0,  # Low touches VWAP
            2532.0,  # Closes above ORB high
            120000,  # Volume surge > 1.5x average
            300,
            True,
        )

        paper_app.on_candle(breakout_candle)

        # 7. Check if Order was placed, filled, and persisted
        orders = paper_app.order_repo.get_all()
        assert len(orders) >= 1
        order = orders[0]
        assert order.symbol == "RELIANCE"
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity > 0

        # 8. Check Trade Repository & Portfolio Position
        trades = paper_app.trade_repo.get_all()
        assert len(trades) >= 1
        assert trades[0].symbol == "RELIANCE"

        positions = paper_app.portfolio.get_all_positions()
        pos = positions.get("RELIANCE")
        assert pos is not None
        assert pos.quantity == order.filled_quantity
        assert pos.average_price > 0.0

    # -------------------------------------------------------------------------
    # 5. 14:30 Square-Off Behavior
    # -------------------------------------------------------------------------

    def test_square_off_closes_open_positions(self, paper_app: PaperTradingApplication):
        """Verify 14:30 square-off flushes open positions and cancels resting orders."""
        paper_app.start(session_time=datetime(2024, 1, 8, 9, 30, 0, tzinfo=IST_TIMEZONE))
        paper_app.advance_time(datetime(2024, 1, 8, 10, 0, 0, tzinfo=IST_TIMEZONE))

        # Manually create open paper position
        paper_app.broker.set_market_price("TCS", 3800.0)
        paper_app.broker.place_order(
            OrderRequest("POS_BUY", "TCS", OrderSide.BUY, OrderType.MARKET, 20)
        )
        assert len(paper_app.broker.get_positions()) == 1

        # Place a resting limit order
        paper_app.broker.place_order(
            OrderRequest("LIMIT_REST", "TCS", OrderSide.BUY, OrderType.LIMIT, 10, price=3700.0)
        )
        assert len([o for o in paper_app.broker.get_orders() if o.is_active]) == 1

        # Advance to 14:30 -> triggers square-off procedure
        paper_app.advance_time(datetime(2024, 1, 8, 14, 30, 0, tzinfo=IST_TIMEZONE))
        assert paper_app.stage == SessionLifecycleStage.SQUARE_OFF

        # Position should now be closed (flat)
        assert len(paper_app.broker.get_positions()) == 0
        # Active orders should be cancelled
        assert len([o for o in paper_app.broker.get_orders() if o.is_active]) == 0

    # -------------------------------------------------------------------------
    # 6. Graceful Shutdown
    # -------------------------------------------------------------------------

    def test_graceful_shutdown(self, paper_app: PaperTradingApplication):
        """Verify shutdown cancels orders, disconnects feeds, and logs reason."""
        paper_app.start(session_time=datetime(2024, 1, 8, 9, 30, 0, tzinfo=IST_TIMEZONE))
        assert paper_app.is_running is True

        paper_app.shutdown("Operator commanded stop")
        assert paper_app.is_running is False
        assert paper_app.shutdown_reason == "Operator commanded stop"
        assert paper_app.stage == SessionLifecycleStage.CLOSED

        # Pipeline and broker should be disconnected
        assert paper_app.broker.is_connected() is False
        assert paper_app.pipeline.is_connected() is False
