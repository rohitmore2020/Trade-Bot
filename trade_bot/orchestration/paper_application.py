"""
Real-Time Paper-Trading Application Orchestrator.

Composes existing modules through dependency injection:
Market Data -> Candle Engine -> Indicators -> Scanner/Candidate State -> Strategy ->
Risk -> Paper Execution -> Portfolio -> Persistence -> Monitoring.

Implements strict session lifecycle:
PRE_MARKET -> MARKET_OPEN -> ORB_PERIOD -> TRADING -> SQUARE_OFF -> CLOSED.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from trade_bot.broker.paper_adapter import PaperBrokerAdapter
from trade_bot.config.constants import (
    IST_TIMEZONE,
    MARKET_CLOSE_TIME,
    MARKET_OPEN_TIME,
    ORB_END_TIME,
    SQUARE_OFF_TIME,
)
from trade_bot.config.settings import AppConfig, ExecutionMode
from trade_bot.data.events import MarketDataEvent, MarketEventType
from trade_bot.data.pipeline import RealtimeMarketDataPipeline
from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType, ProductType, SignalDirection
from trade_bot.domain.exceptions import ConfigurationError
from trade_bot.domain.models import Candle, Order, OrderRequest, Tick, Trade
from trade_bot.indicators.engine import IndicatorEngine
from trade_bot.indicators.interfaces import IndicatorSnapshot
from trade_bot.observability.audit import AuditLogger
from trade_bot.observability.metrics import MetricsCollector
from trade_bot.persistence.interfaces import IOrderRepository, ITradeRepository
from trade_bot.portfolio.manager import PortfolioManager
from trade_bot.risk.decision_engine import RiskDecisionEngine
from trade_bot.risk.models import RiskAssessmentContext, TradeProposal
from trade_bot.scanner.interfaces import ICandidateScanner
from trade_bot.scanner.scanner import CandidateScanner
from trade_bot.strategy.engine import VWAPORBStrategyEngine
from trade_bot.strategy.models import UniverseCandidate, VwapOrbSignal

logger = logging.getLogger(__name__)


class SessionLifecycleStage(str, Enum):
    """Session lifecycle stages for intraday trading."""
    PRE_MARKET = "PRE_MARKET"      # 09:00 - 09:15
    MARKET_OPEN = "MARKET_OPEN"    # 09:15
    ORB_PERIOD = "ORB_PERIOD"      # 09:15 - 09:30
    TRADING = "TRADING"            # 09:30 - 14:30
    SQUARE_OFF = "SQUARE_OFF"      # 14:30 - 15:30
    CLOSED = "CLOSED"              # >= 15:30


class PaperTradingApplication:
    """
    Production-grade Paper-Trading Application Container.
    Assembles and coordinates the end-to-end platform for paper trading.
    """

    def __init__(
        self,
        config: AppConfig,
        market_data_pipeline: RealtimeMarketDataPipeline,
        indicator_engine: IndicatorEngine,
        scanner: ICandidateScanner | CandidateScanner,
        strategy_engine: VWAPORBStrategyEngine,
        risk_engine: RiskDecisionEngine,
        broker: PaperBrokerAdapter,
        portfolio: PortfolioManager,
        order_repository: IOrderRepository,
        trade_repository: ITradeRepository,
        audit_logger: AuditLogger,
        metrics_collector: MetricsCollector,
        symbol_sector_map: Optional[Dict[str, str]] = None,
    ) -> None:
        self.config = config
        self._validate_configuration(config)
        self.symbol_sector_map: Dict[str, str] = dict(symbol_sector_map or {})

        # Injected Components
        self.pipeline = market_data_pipeline
        self.indicator_engine = indicator_engine
        self.scanner = scanner
        self.strategy_engine = strategy_engine
        self.risk_engine = risk_engine
        self.broker = broker
        self.portfolio = portfolio
        self.order_repo = order_repository
        self.trade_repo = trade_repository
        self.audit = audit_logger
        self.metrics = metrics_collector

        # Lifecycle State
        self.stage: SessionLifecycleStage = SessionLifecycleStage.PRE_MARKET
        self._is_running: bool = False
        self._shutdown_reason: Optional[str] = None
        self._current_session_date: Optional[datetime] = None
        self._order_counter: int = 0

        # Wire pipeline callbacks
        self.pipeline.register_candle_listener(self.on_candle)
        self.pipeline.register_event_listener(self._on_market_data_event)
        self.broker.register_trade_callback(self._on_trade_fill)
        self.broker.register_order_callback(self._on_order_update)

    @classmethod
    def _validate_configuration(cls, config: AppConfig) -> None:
        """Enforces that application is running strictly in PAPER mode."""
        if config.system.mode != ExecutionMode.PAPER:
            raise ConfigurationError(
                f"PaperTradingApplication requires MODE=paper, got MODE={config.system.mode.value}. "
                "Failing safely to prevent unintended execution."
            )
        if config.risk.initial_capital <= 0:
            raise ConfigurationError("initial_capital must be positive")

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def shutdown_reason(self) -> Optional[str]:
        return self._shutdown_reason

    # -------------------------------------------------------------------------
    # Lifecycle Management
    # -------------------------------------------------------------------------

    def start(self, session_time: Optional[datetime] = None) -> None:
        """Start the paper-trading application."""
        if self._is_running:
            logger.warning("PaperTradingApplication is already running.")
            return

        now = session_time or datetime.now(IST_TIMEZONE)
        self._current_session_date = now
        self._is_running = True
        self._shutdown_reason = None

        self.audit.record_event("APPLICATION_STARTED", {"mode": "paper", "time": now.isoformat()})

        # Connect market data pipeline and paper broker
        self.broker.connect()
        self.pipeline.connect()

        self.advance_time(now)
        logger.info("PaperTradingApplication started successfully at %s in stage %s", now, self.stage)

    def advance_time(self, current_time: datetime) -> SessionLifecycleStage:
        """
        Progress session lifecycle stage based on Indian NSE equity schedule:
        - 09:00 - 09:15: PRE_MARKET
        - 09:15: MARKET_OPEN
        - 09:15 - 09:30: ORB_PERIOD
        - 09:30 - 14:30: TRADING
        - 14:30 - 15:30: SQUARE_OFF
        - >= 15:30: CLOSED
        """
        if not self._is_running:
            return self.stage

        t = current_time.time()
        prev_stage = self.stage

        if t < MARKET_OPEN_TIME:
            new_stage = SessionLifecycleStage.PRE_MARKET
        elif t == MARKET_OPEN_TIME and prev_stage == SessionLifecycleStage.PRE_MARKET:
            new_stage = SessionLifecycleStage.MARKET_OPEN
        elif t < ORB_END_TIME:
            new_stage = SessionLifecycleStage.ORB_PERIOD
        elif t < SQUARE_OFF_TIME:
            new_stage = SessionLifecycleStage.TRADING
        elif t < MARKET_CLOSE_TIME:
            new_stage = SessionLifecycleStage.SQUARE_OFF
        else:
            new_stage = SessionLifecycleStage.CLOSED

        if new_stage != prev_stage:
            self._transition_stage(new_stage, current_time)

        return self.stage

    def _transition_stage(self, new_stage: SessionLifecycleStage, current_time: datetime) -> None:
        """Handle side effects of transitioning into a new lifecycle stage."""
        old_stage = self.stage
        self.stage = new_stage
        logger.info("Session lifecycle transition: %s -> %s at %s", old_stage, new_stage, current_time.time())

        self.audit.record_event(
            "SESSION_LIFECYCLE_CHANGED",
            {"old_stage": old_stage.value, "new_stage": new_stage.value, "time": current_time.isoformat()},
        )

        if new_stage == SessionLifecycleStage.MARKET_OPEN:
            self._handle_market_open(current_time)
            # Immediately transition to ORB_PERIOD for processing
            self.stage = SessionLifecycleStage.ORB_PERIOD
        elif new_stage == SessionLifecycleStage.SQUARE_OFF:
            self._handle_square_off(current_time)
        elif new_stage == SessionLifecycleStage.CLOSED:
            self._handle_session_close(current_time)

    def _handle_market_open(self, session_date: datetime) -> None:
        """Execute market open boundaries (09:15 IST)."""
        self.strategy_engine.reset_session()
        self.portfolio.reset_daily_session(trading_date=session_date.date())
        self.pipeline.handle_market_open(session_date)
        self.audit.record_event("MARKET_OPEN_INITIALIZED", {"time": session_date.isoformat()})

    def _handle_square_off(self, current_time: datetime) -> None:
        """Execute 14:30 IST square-off procedure: close open positions, disallow new entries."""
        logger.info("Executing 14:30 intraday square-off procedure...")
        open_positions = self.broker.get_positions()
        for pos in open_positions:
            if not pos.is_flat:
                self._execute_market_exit(
                    symbol=pos.symbol,
                    quantity=abs(pos.quantity),
                    side=OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY,
                    reason="TIME_EXIT_1430",
                    timestamp=current_time,
                )

        # Cancel any remaining resting limit/stop orders
        active_orders = [o for o in self.broker.get_orders() if o.is_active]
        for ord_obj in active_orders:
            if ord_obj.broker_order_id:
                self.broker.cancel_order(ord_obj.broker_order_id)

    def _handle_session_close(self, current_time: datetime) -> None:
        """Execute session close at 15:30 IST."""
        logger.info("Closing session at 15:30 IST...")
        self.pipeline.handle_market_close(current_time)
        self.audit.record_event("SESSION_CLOSED", {"time": current_time.isoformat()})

    # -------------------------------------------------------------------------
    # Pre-Market Scanning
    # -------------------------------------------------------------------------

    def run_premarket_scan(self, candidates: List[UniverseCandidate]) -> List[str]:
        """
        Filter universe candidates during PRE_MARKET (09:00 - 09:15).
        Stores eligible universe in strategy engine and subscribes in market data pipeline.
        """
        logger.info("Running pre-market screening on %d candidates...", len(candidates))
        eligible_symbols = self.strategy_engine.set_eligible_universe(candidates)

        # Subscribe eligible universe to market data pipeline
        if eligible_symbols:
            self.pipeline.subscribe(eligible_symbols)
            self.broker.subscribe(eligible_symbols) if hasattr(self.broker, "subscribe") else None

        self.audit.record_event(
            "PREMARKET_SCAN_COMPLETED",
            {"total_candidates": len(candidates), "eligible_symbols": eligible_symbols},
        )
        return eligible_symbols

    # -------------------------------------------------------------------------
    # Real-Time Market Processing
    # -------------------------------------------------------------------------

    def on_tick(self, tick: Tick) -> None:
        """Ingest live/simulated market tick across all components."""
        if not self._is_running:
            return

        self.metrics.record_tick()
        self.advance_time(tick.timestamp)

        # Update paper broker and portfolio reference prices
        self.broker.on_tick(tick)
        self.portfolio.update_market_price(tick.symbol, tick.last_price)

        # Dispatch tick into market data pipeline for deduplication & 5-minute candle building
        event = MarketDataEvent(
            event_type=MarketEventType.TICK,
            timestamp=tick.timestamp,
            symbol=tick.symbol,
            data=tick,
        )
        self.pipeline._on_provider_event(event)

    def on_candle(self, candle: Candle) -> None:
        """
        Handle a closed 5-minute candle emitted by RealtimeCandleAggregator.
        Executes indicator calculation, signal evaluation, risk sizing, and paper order submission.
        """
        if not self._is_running:
            return

        self.metrics.record_candle()
        self.advance_time(candle.timestamp)
        symbol = candle.symbol

        # Check if benchmark index candle
        if symbol.upper() in ("^NSEI", "NIFTY", "NIFTY 50", "NIFTY50"):
            self.indicator_engine.nifty_indicator.update_candle(candle)
            return

        # 1. Update indicators and compute snapshot
        snapshot = self.indicator_engine.process_candle(candle)

        # 2. Lifecycle gate: No entries during PRE_MARKET or ORB_PERIOD
        if self.stage in (SessionLifecycleStage.PRE_MARKET, SessionLifecycleStage.ORB_PERIOD):
            # In ORB period, candle is ingested to establish ORB high/low, but trade entries are disallowed
            return

        # 3. In SQUARE_OFF or CLOSED: Disallow new entries, enforce exits
        if self.stage in (SessionLifecycleStage.SQUARE_OFF, SessionLifecycleStage.CLOSED):
            return

        # 4. In TRADING stage: Evaluate strategy entry and exit rules
        if self.stage == SessionLifecycleStage.TRADING:
            signal = self.strategy_engine.process_candle(candle, snapshot)
            if signal:
                self._handle_strategy_signal(signal, candle, snapshot)

    def _handle_strategy_signal(
        self,
        signal: VwapOrbSignal,
        candle: Candle,
        snapshot: IndicatorSnapshot,
    ) -> None:
        """Process signal emitted by VWAPORBStrategyEngine."""
        self.metrics.record_signal()
        self.audit.record_event(
            "SIGNAL_GENERATED",
            {
                "symbol": signal.symbol,
                "direction": signal.direction.value,
                "entry_price": signal.entry_price,
                "stop_price": signal.stop_price,
                "reason": signal.reason,
            },
        )

        # A. Exit Signal
        if signal.direction == SignalDirection.FLAT:
            # Active position exit
            pos = next((p for p in self.broker.get_positions() if p.symbol == signal.symbol), None)
            if pos and not pos.is_flat:
                self._execute_market_exit(
                    symbol=signal.symbol,
                    quantity=abs(pos.quantity),
                    side=OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY,
                    reason="STRATEGY_EXIT",
                    timestamp=candle.timestamp,
                )
            return

        # B. Entry Signal (LONG or SHORT)
        side = OrderSide.BUY if signal.direction == SignalDirection.LONG else OrderSide.SELL
        sector = self.symbol_sector_map.get(signal.symbol, "GENERAL_EQUITY")
        proposal = TradeProposal(
            symbol=signal.symbol,
            side=side,
            entry_price=signal.entry_price or candle.close,
            stop_loss_price=signal.stop_price or (candle.close * 0.99),
            sector=sector,
            timestamp=candle.timestamp,
        )

        # Assess Risk
        balance = self.portfolio.get_account_balance()
        open_positions = {p.symbol: p for p in self.portfolio.get_all_positions() if not p.is_flat}
        sector_map = {**self.symbol_sector_map, signal.symbol: sector}
        risk_context = RiskAssessmentContext(
            equity=balance.total_equity,
            available_cash=balance.available_cash,
            daily_realized_pnl=balance.total_realized_pnl,
            daily_unrealized_pnl=balance.total_unrealized_pnl,
            daily_executed_trades=self.strategy_engine.daily_trade_count,
            current_positions=open_positions,
            symbol_sector_map=sector_map,
            market_regime=snapshot.nifty_regime,
        )

        decision = self.risk_engine.evaluate(proposal, risk_context)

        if not decision.is_approved or decision.approved_quantity <= 0:
            logger.info("Signal rejected by risk engine for %s: %s", signal.symbol, decision.reason)
            self.metrics.record_risk_violation()
            self.audit.record_event(
                "SIGNAL_RISK_REJECTED",
                {"symbol": signal.symbol, "reason": decision.reason, "rule": decision.rule_name},
            )
            return

        # Approved by Risk -> Create Paper OrderRequest
        self._order_counter += 1
        client_order_id = f"PAPER_ORD_{self._order_counter:06d}"
        signal_id = f"SIG_{signal.symbol}_{int(candle.timestamp.timestamp())}"

        order_req = OrderRequest(
            client_order_id=client_order_id,
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=decision.approved_quantity,
            price=candle.close,
            stop_loss=signal.stop_price,
            product_type=ProductType.MIS,
            strategy_name="VWAP_ORB_V1.0",
            signal_id=signal_id,
        )

        # Place order with PaperBrokerAdapter
        self.metrics.record_order_submitted()
        broker_id = self.broker.place_order(order_req)
        logger.info("Placed paper order %s (Broker ID: %s) for %d %s", client_order_id, broker_id, decision.approved_quantity, signal.symbol)

    def _execute_market_exit(
        self,
        symbol: str,
        quantity: int,
        side: OrderSide,
        reason: str,
        timestamp: datetime,
    ) -> None:
        """Submit a paper market exit order."""
        self._order_counter += 1
        client_order_id = f"PAPER_EXIT_{self._order_counter:06d}"
        exit_req = OrderRequest(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            product_type=ProductType.MIS,
            strategy_name="VWAP_ORB_EXIT",
            tag=reason,
        )
        self.metrics.record_order_submitted()
        self.broker.place_order(exit_req)
        logger.info("Executed paper exit for %s: %d shares %s (reason: %s)", symbol, quantity, side.value, reason)

    # -------------------------------------------------------------------------
    # Callbacks & Persistence
    # -------------------------------------------------------------------------

    def _on_trade_fill(self, trade: Trade) -> None:
        """Handle execution trade fill callback from PaperBrokerAdapter."""
        self.metrics.record_order_filled()
        self.portfolio.process_fill(trade)
        self.trade_repo.save(trade)
        self.audit.record_event(
            "PAPER_TRADE_FILLED",
            {
                "trade_id": trade.trade_id,
                "order_id": trade.order_id,
                "symbol": trade.symbol,
                "side": trade.side.value,
                "quantity": trade.quantity,
                "price": trade.price,
            },
        )

    def _on_order_update(self, order: Order) -> None:
        """Handle order status change from PaperBrokerAdapter."""
        if order.status == OrderStatus.REJECTED:
            self.metrics.record_order_rejected()
        self.order_repo.save(order)
        self.audit.record_event(
            "PAPER_ORDER_UPDATED",
            {
                "client_order_id": order.client_order_id,
                "broker_order_id": order.broker_order_id,
                "status": order.status.value,
                "filled_quantity": order.filled_quantity,
            },
        )

    def _on_market_data_event(self, event: MarketDataEvent) -> None:
        """Forward health alerts or status changes from pipeline."""
        if event.event_type == MarketEventType.STALE_DATA_ALERT:
            logger.warning("Stale data alert received for %s", event.symbol)
            self.audit.record_event("STALE_DATA_ALERT", {"symbol": event.symbol, "details": event.data})

    # -------------------------------------------------------------------------
    # Graceful Shutdown
    # -------------------------------------------------------------------------

    def shutdown(self, reason: str = "Client requested shutdown") -> None:
        """
        Graceful shutdown:
        1. Stops accepting new signals
        2. Cancels all active paper orders
        3. Persists final state
        4. Closes resources cleanly
        5. Records shutdown reason
        """
        if not self._is_running:
            return

        logger.info("Initiating graceful shutdown of PaperTradingApplication: %s", reason)
        self._is_running = False
        self._shutdown_reason = reason
        self.stage = SessionLifecycleStage.CLOSED

        # 1. Cancel active working orders
        active_orders = [o for o in self.broker.get_orders() if o.is_active]
        for o in active_orders:
            if o.broker_order_id:
                self.broker.cancel_order(o.broker_order_id)

        # 2. Flush and disconnect market data pipeline
        self.pipeline.disconnect()
        self.broker.disconnect()

        # 3. Record audit event
        self.audit.record_event(
            "APPLICATION_SHUTDOWN",
            {
                "reason": reason,
                "total_trades": len(self.trade_repo.get_all()),
                "total_orders": len(self.order_repo.get_all()),
                "portfolio_balance": self.portfolio.get_account_balance().total_equity,
            },
        )
        logger.info("Graceful shutdown complete.")
