"""
Trading Engine Orchestrator.

Coordinates lifecycle, data flow between market data feeds, strategy evaluation,
risk verification, execution engine, portfolio updates, and metrics collection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from trade_bot.config.settings import AppConfig
from trade_bot.data.aggregator import TimeframeCandleAggregator
from trade_bot.data.interfaces import IMarketDataProvider
from trade_bot.domain.models import Candle, Signal, Tick
from trade_bot.execution.interfaces import IExecutionEngine
from trade_bot.observability.audit import AuditLogger
from trade_bot.observability.logger import get_logger
from trade_bot.observability.metrics import MetricsCollector
from trade_bot.portfolio.interfaces import IPortfolioManager
from trade_bot.risk.interfaces import IRiskManager
from trade_bot.strategy.base import IStrategy, StrategyContext

logger = get_logger("orchestration.engine")


class TradingEngine:
    """
    Central operational session orchestrating application components.
    """

    def __init__(
        self,
        config: AppConfig,
        market_data_provider: IMarketDataProvider,
        execution_engine: IExecutionEngine,
        portfolio_manager: IPortfolioManager,
        risk_manager: IRiskManager,
        candle_aggregator_1m: TimeframeCandleAggregator,
        candle_aggregator_5m: TimeframeCandleAggregator,
        audit_logger: AuditLogger,
        metrics_collector: MetricsCollector,
        strategy: Optional[IStrategy] = None,
    ) -> None:
        self.config = config
        self.market_data = market_data_provider
        self.execution = execution_engine
        self.portfolio = portfolio_manager
        self.risk = risk_manager
        self.aggregator_1m = candle_aggregator_1m
        self.aggregator_5m = candle_aggregator_5m
        self.audit = audit_logger
        self.metrics = metrics_collector
        self.strategy = strategy

        self._is_running: bool = False
        self._subscribed_symbols: List[str] = []
        self._active_candles_1m: Dict[str, Candle] = {}
        self._active_candles_5m: Dict[str, Candle] = {}

        # Wire callbacks
        self.market_data.register_tick_handler(self.on_tick)
        self.aggregator_1m.register_candle_handler(self.on_candle_1m)
        self.aggregator_5m.register_candle_handler(self.on_candle_5m)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self, symbols: List[str]) -> None:
        """Start trading engine and subscribe to universe."""
        if self._is_running:
            logger.warning("TradingEngine is already running")
            return

        logger.info(
            "Starting TradingEngine in %s mode for symbols: %s",
            self.config.system.mode.value,
            symbols,
        )
        self._subscribed_symbols = symbols
        self.market_data.connect()
        self.market_data.subscribe(symbols)

        if self.strategy:
            self.strategy.on_start(symbols)

        self._is_running = True
        self.audit.record_event(
            "ENGINE_STARTED",
            {"mode": self.config.system.mode.value, "symbols": symbols},
        )

    def stop(self) -> None:
        """Gracefully stop trading engine."""
        if not self._is_running:
            return

        logger.info("Stopping TradingEngine")
        if self.strategy:
            self.strategy.on_stop()

        self.market_data.unsubscribe(self._subscribed_symbols)
        self.market_data.disconnect()

        # Flush forming candles
        self.aggregator_1m.flush()
        self.aggregator_5m.flush()

        self._is_running = False
        self.audit.record_event("ENGINE_STOPPED", {})

    def on_tick(self, tick: Tick) -> None:
        """Process incoming tick across aggregators and strategy."""
        if not self._is_running:
            return

        self.metrics.record_tick()
        self.portfolio.update_market_price(tick.symbol, tick.last_price)

        # Aggregate candles
        self.aggregator_1m.process_tick(tick)
        self.aggregator_5m.process_tick(tick)

        # Evaluate strategy on tick if enabled
        if self.strategy:
            context = StrategyContext(
                current_time=tick.timestamp,
                positions=self.portfolio.get_all_positions(),
                account_balance=self.portfolio.get_account_balance(),
                active_candles_1m=dict(self._active_candles_1m),
                active_candles_5m=dict(self._active_candles_5m),
            )
            signals = self.strategy.on_tick(tick, context)
            for sig in signals:
                self._handle_signal(sig)

    def on_candle_1m(self, candle: Candle) -> None:
        """Process 1-minute closed candle."""
        self._active_candles_1m[candle.symbol] = candle
        self.metrics.record_candle()

    def on_candle_5m(self, candle: Candle) -> None:
        """Process 5-minute closed candle and trigger strategy on_candle."""
        self._active_candles_5m[candle.symbol] = candle

        if self.strategy:
            context = StrategyContext(
                current_time=candle.timestamp,
                positions=self.portfolio.get_all_positions(),
                account_balance=self.portfolio.get_account_balance(),
                active_candles_1m=dict(self._active_candles_1m),
                active_candles_5m=dict(self._active_candles_5m),
            )
            signals = self.strategy.on_candle(candle, context)
            for sig in signals:
                self._handle_signal(sig)

    def _handle_signal(self, signal: Signal) -> None:
        """Record and process strategy signal."""
        self.metrics.record_signal()
        self.audit.record_event(
            "SIGNAL_GENERATED",
            {
                "signal_id": signal.signal_id,
                "symbol": signal.symbol,
                "direction": signal.direction.value,
                "entry_price": signal.entry_price,
            },
        )
