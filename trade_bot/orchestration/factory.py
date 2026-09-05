"""
Trading Engine Dependency Injection Factory.

Assembles and wires modular components according to execution mode (BACKTEST, PAPER, LIVE).
"""

from __future__ import annotations

from typing import Optional
from trade_bot.broker.backtest_adapter import BacktestBrokerAdapter
from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.broker.paper_adapter import PaperBrokerAdapter
from trade_bot.broker.upstox_adapter import UpstoxBrokerAdapter
from trade_bot.config.settings import AppConfig, ExecutionMode
from trade_bot.data.aggregator import TimeframeCandleAggregator
from trade_bot.data.interfaces import IMarketDataProvider
from trade_bot.data.memory_data_feed import InMemoryMarketDataFeed
from trade_bot.domain.exceptions import ConfigurationError
from trade_bot.execution.engine import ExecutionEngine
from trade_bot.execution.idempotency import IdempotencyManager
from trade_bot.observability.audit import AuditLogger
from trade_bot.observability.logger import configure_logging
from trade_bot.observability.metrics import MetricsCollector
from trade_bot.orchestration.engine import TradingEngine
from trade_bot.portfolio.manager import PortfolioManager
from trade_bot.risk.manager import RiskManager
from trade_bot.strategy.base import IStrategy


class TradingEngineFactory:
    """
    Factory for constructing fully wired TradingEngine instances based on configuration.
    """

    @classmethod
    def create_broker_adapter(cls, config: AppConfig) -> IBrokerAdapter:
        """Instantiate appropriate broker adapter based on mode."""
        mode = config.system.mode
        if mode == ExecutionMode.BACKTEST:
            return BacktestBrokerAdapter(config=config.broker)
        elif mode == ExecutionMode.PAPER:
            return PaperBrokerAdapter(config=config.broker)
        elif mode == ExecutionMode.LIVE:
            if not config.system.allow_live_trading:
                raise ConfigurationError(
                    "Cannot build LIVE broker adapter: allow_live_trading is False"
                )
            return UpstoxBrokerAdapter(
                config=config.broker,
                allow_live=config.system.allow_live_trading,
            )
        raise ConfigurationError(f"Unsupported execution mode: {mode}")

    @classmethod
    def create_market_data_provider(cls, config: AppConfig) -> IMarketDataProvider:
        """Instantiate market data provider based on mode."""
        # For Phase 0, in-memory data feed is used for backtest and test sessions
        return InMemoryMarketDataFeed()

    @classmethod
    def build_engine(
        cls,
        config: AppConfig,
        strategy: Optional[IStrategy] = None,
        custom_market_data: Optional[IMarketDataProvider] = None,
        custom_broker: Optional[IBrokerAdapter] = None,
    ) -> TradingEngine:
        """Build and wire all platform layers together."""
        # Observability
        configure_logging(config.logging)
        audit_logger = AuditLogger(audit_dir=config.logging.audit_dir)
        metrics_collector = MetricsCollector()

        # Broker & Data Layer
        broker = custom_broker or cls.create_broker_adapter(config)
        market_data = custom_market_data or cls.create_market_data_provider(config)

        # Risk & Portfolio Layer
        risk_manager = RiskManager(config=config.risk)
        portfolio_manager = PortfolioManager(initial_capital=config.risk.initial_capital)

        # Execution Engine
        idempotency = IdempotencyManager()
        execution_engine = ExecutionEngine(
            broker=broker,
            risk_manager=risk_manager,
            portfolio_manager=portfolio_manager,
            idempotency_manager=idempotency,
        )

        # Wire broker execution fills into ExecutionEngine
        broker.register_trade_callback(execution_engine.handle_fill)

        # Aggregators
        aggregator_1m = TimeframeCandleAggregator(timeframe_seconds=60)
        aggregator_5m = TimeframeCandleAggregator(timeframe_seconds=300)

        return TradingEngine(
            config=config,
            market_data_provider=market_data,
            execution_engine=execution_engine,
            portfolio_manager=portfolio_manager,
            risk_manager=risk_manager,
            candle_aggregator_1m=aggregator_1m,
            candle_aggregator_5m=aggregator_5m,
            audit_logger=audit_logger,
            metrics_collector=metrics_collector,
            strategy=strategy,
        )
