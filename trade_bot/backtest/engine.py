"""
Deterministic Event-Driven Backtesting Engine.

Coordinates the complete trading pipeline:
Historical Market Data
→ NSE Calendar & Session
→ IndicatorEngine
→ CandidateScanner
→ VwapOrbPureStrategy
→ RiskDecisionEngine
→ ExecutionSimulator
→ PortfolioManager
→ BacktestAnalytics
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from trade_bot.backtest.analytics import BacktestAnalytics
from trade_bot.backtest.clock import SimulationClock
from trade_bot.backtest.data_feed import HistoricalDataFeed
from trade_bot.backtest.interfaces import IBacktestRunner
from trade_bot.backtest.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    DailyPnLSummary,
)
from trade_bot.backtest.simulator import ExecutionSimulator
from trade_bot.data.calendar import NSETradingCalendar
from trade_bot.domain.enums import (
    MarketRegime,
    OrderSide,
    OrderStatus,
    TradingSessionStatus,
)
from trade_bot.domain.models import Candle, OrderRequest
from trade_bot.indicators.engine import IndicatorEngine
from trade_bot.indicators.interfaces import IndicatorSnapshot
from trade_bot.portfolio.manager import PortfolioManager
from trade_bot.portfolio.models import CompletedTrade
from trade_bot.risk.decision_engine import RiskDecisionEngine
from trade_bot.risk.models import RiskAssessmentContext, RiskParameters
from trade_bot.scanner.scanner import CandidateScanner
from trade_bot.strategy.models import StrategyMarketInput, TradeIntent, VwapOrbStrategyConfig
from trade_bot.strategy.pure_strategy import VwapOrbPureStrategy
from trade_bot.strategy.state import ExitReason, PositionStatus, StrategyTradeState


class BacktestEngine(IBacktestRunner):
    """
    Deterministic event-driven backtesting engine for the Indian NSE VWAP-ORB strategy.
    Reuses existing IndicatorEngine, CandidateScanner, PureStrategy, RiskEngine, and PortfolioManager.
    """

    def __init__(
        self,
        config: Optional[BacktestConfig] = None,
        data_feed: Optional[HistoricalDataFeed] = None,
        strategy_config: Optional[VwapOrbStrategyConfig] = None,
        risk_params: Optional[RiskParameters] = None,
        scanner: Optional[CandidateScanner] = None,
        cost_model: Optional[Any] = None,
    ) -> None:
        self.config = config or BacktestConfig()
        self.data_feed = data_feed or HistoricalDataFeed()
        self.calendar = NSETradingCalendar()
        self.clock = SimulationClock(calendar=self.calendar)

        # Core Domain Modules (reused without modification)
        self.portfolio = PortfolioManager(
            initial_capital=self.config.initial_capital,
            currency=self.config.currency,
            max_daily_loss_pct=self.config.max_daily_loss_pct,
            max_trades_limit=self.config.max_daily_trades,
            max_positions_limit=self.config.max_open_positions,
            max_sector_exposure_pct=0.40,
        )

        self.indicators = IndicatorEngine(
            atr_period=14,
            volume_sma_period=10,
            min_gap_pct=1.0,
        )

        self.strategy = VwapOrbPureStrategy(config=strategy_config)
        self.risk_engine = RiskDecisionEngine(params=risk_params or RiskParameters(
            max_risk_per_trade_pct=self.config.risk_per_trade_pct,
            max_capital_per_trade_pct=self.config.max_capital_per_trade_pct,
            max_daily_trades=self.config.max_daily_trades,
            max_open_positions=self.config.max_open_positions,
            max_daily_loss_pct=self.config.max_daily_loss_pct,
        ))
        self.scanner = scanner or CandidateScanner()

        # Execution Simulator
        self.simulator = ExecutionSimulator(
            portfolio_manager=self.portfolio,
            slippage_per_share=self.config.slippage_per_share,
            slippage_pct=self.config.slippage_pct,
            default_limit_timeout_bars=self.config.limit_timeout_bars,
            cost_model=cost_model,
        )

        # Per-symbol Strategy State
        self._strategy_states: Dict[str, StrategyTradeState] = {}
        # Client order ID to target stop price mapping for pending limits
        self._pending_stop_prices: Dict[str, float] = {}

        # Performance Tracking
        self._equity_curve: List[Tuple[datetime, float]] = []
        self._equity_by_date: Dict[date, List[float]] = defaultdict(list)
        self._current_session_date: Optional[date] = None
        self._total_turnover: float = 0.0
        self._peak_exposure: float = 0.0
        self._exposure_samples: List[float] = []
        self._total_slippage: float = 0.0

    def _get_or_create_strategy_state(self, symbol: str) -> StrategyTradeState:
        sym = symbol.upper().strip()
        if sym not in self._strategy_states:
            self._strategy_states[sym] = StrategyTradeState(
                symbol=sym,
                max_trades_per_session=2,
            )
        return self._strategy_states[sym]

    def _handle_session_transition(self, current_date: date) -> None:
        """Handles daily boundary reset across all components."""
        if self._current_session_date is None or current_date > self._current_session_date:
            self._current_session_date = current_date

            # Reset portfolio daily counters and roll initial capital
            self.portfolio.reset_daily_session(trading_date=current_date)

            # Reset strategy state per symbol
            for state in self._strategy_states.values():
                state.reset_session()

            # Seed previous day closes into indicator coordinators
            for sym in self.config.symbols:
                prev_close = self.data_feed.get_previous_session_close(sym, current_date)
                if prev_close is not None:
                    coord = self.indicators._get_or_create_coordinator(sym)
                    coord.set_previous_day_close(prev_close)

    def run(self) -> BacktestResult:
        """
        Executes the backtest bar-by-bar across the entire dataset.
        Enforces strict zero look-ahead bias at every step.
        """
        execution_start = datetime.now()

        # Stream bars in strict chronological order
        for timestamp, bars in self.data_feed.stream_bars():
            self.clock.advance_to(timestamp)
            current_date = timestamp.date()

            # Step 1: Session Management & Daily Resets
            self._handle_session_transition(current_date)

            # Extract Macro Context (NIFTY & VIX)
            nifty_candle = bars.get(self.config.nifty_symbol)
            vix_value = self.data_feed.get_vix_for_timestamp(timestamp)

            # Step 2: Simulate Order Execution against Bar Price Action
            # (Pending limits and stop-losses from previous bars)
            for sym, candle in bars.items():
                if sym == self.config.nifty_symbol or sym == self.config.vix_symbol:
                    continue

                state = self._get_or_create_strategy_state(sym)
                fills = self.simulator.process_bar(candle)

                for fill in fills:
                    self._total_turnover += (fill.price * fill.quantity)
                    slip = abs(fill.price - candle.close) * fill.quantity * 0.1
                    self._total_slippage += slip

                    # Handle Entry Fill (LIMIT order hit)
                    if fill.side in (OrderSide.BUY, OrderSide.SELL) and state.position_status == PositionStatus.PENDING_ENTRY:
                        stop_price = self._pending_stop_prices.pop(fill.client_order_id, None)
                        if stop_price is None:
                            # Fallback 1.5 ATR stop
                            atr = self.indicators.get_atr(sym) or (fill.price * 0.02)
                            stop_price = fill.price - (1.5 * atr) if fill.side == OrderSide.BUY else fill.price + (1.5 * atr)

                        # Open trade in strategy state
                        state.open_trade(
                            timestamp=fill.timestamp,
                            entry_price=fill.price,
                            initial_stop=stop_price,
                            side=fill.side,
                        )

                        # Set stop loss in simulator
                        exit_side = OrderSide.SELL if fill.side == OrderSide.BUY else OrderSide.BUY
                        self.simulator.set_stop_loss(
                            symbol=sym,
                            side=exit_side,
                            stop_price=stop_price,
                            quantity=fill.quantity,
                            parent_order_id=fill.client_order_id,
                            timestamp=fill.timestamp,
                        )

                    # Handle Stop Loss Fill (Intra-bar SL-M hit)
                    elif state.position_status == PositionStatus.OPEN and state.active_trade is not None:
                        if (state.active_trade.side == OrderSide.BUY and fill.side == OrderSide.SELL) or \
                           (state.active_trade.side == OrderSide.SELL and fill.side == OrderSide.BUY):
                            state.close_trade(
                                timestamp=fill.timestamp,
                                exit_price=fill.price,
                                reason=ExitReason.INITIAL_STOP,
                            )

            # Cleanup expired pending limits that timed out
            for sym in self.config.symbols:
                state = self._get_or_create_strategy_state(sym)
                if state.position_status == PositionStatus.PENDING_ENTRY:
                    # Check if pending limit still exists in simulator
                    has_pending = any(p.order.symbol == sym for p in self.simulator._pending_limits.values())
                    if not has_pending:
                        # Order timed out; reset state back to FLAT
                        state.position_status = PositionStatus.FLAT

            # Step 3: Mandatory 14:30 IST Forced Exit
            if self.clock.is_forced_exit_time(timestamp):
                for pos in self.portfolio.get_open_positions():
                    sym = pos.symbol
                    state = self._get_or_create_strategy_state(sym)
                    candle = bars.get(sym)
                    current_price = candle.close if candle else (pos.last_price or pos.average_price)
                    exit_side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY

                    fill = self.simulator.execute_market_exit(
                        symbol=sym,
                        side=exit_side,
                        quantity=pos.quantity,
                        current_price=current_price,
                        timestamp=timestamp,
                        reason="14:30_FORCED_EXIT",
                    )
                    self._total_turnover += (fill.price * fill.quantity)
                    if state.position_status == PositionStatus.OPEN:
                        state.close_trade(
                            timestamp=timestamp,
                            exit_price=fill.price,
                            reason=ExitReason.TIME_EXIT,
                        )

                # Cancel any pending limit orders
                self.simulator.cancel_all_pending(reason="14:30_FORCED_EXIT")

            # Step 4: Update Indicators & Evaluate Strategy Signals
            for sym, candle in bars.items():
                if sym == self.config.nifty_symbol or sym == self.config.vix_symbol:
                    continue

                # Ingest completed 5m candle
                snapshot = self.indicators.process_candle(
                    candle=candle,
                    is_forming=False,
                    nifty_candle=nifty_candle,
                    india_vix=vix_value,
                )

                # Update portfolio mark-to-market
                self.portfolio.update_market_price(sym, candle.close)

                # Strategy evaluation is permitted strictly within trading window (09:45 to 14:30 IST)
                if self.clock.is_trading_window(timestamp) and not self.clock.is_forced_exit_time(timestamp):
                    self._evaluate_strategy_for_symbol(sym, candle, snapshot, nifty_candle)

            # Step 5: Record Equity & Exposure Tracking
            balance = self.portfolio.get_account_balance()
            current_equity = balance.total_equity
            self._equity_curve.append((timestamp, current_equity))
            self._equity_by_date[current_date].append(current_equity)

            current_exposure = sum(p.market_value for p in self.portfolio.get_open_positions())
            self._exposure_samples.append(current_exposure)
            if current_exposure > self._peak_exposure:
                self._peak_exposure = current_exposure

        # End of Backtest: Force square off any remaining positions if any
        final_ts = self.clock.current_time
        for pos in self.portfolio.get_open_positions():
            sym = pos.symbol
            state = self._get_or_create_strategy_state(sym)
            exit_side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
            fill = self.simulator.execute_market_exit(
                symbol=sym,
                side=exit_side,
                quantity=pos.quantity,
                current_price=pos.last_price or pos.average_price,
                timestamp=final_ts,
                reason="BACKTEST_END_SQUAREOFF",
            )
            self._total_turnover += (fill.price * fill.quantity)
            if state.position_status == PositionStatus.OPEN:
                state.close_trade(
                    timestamp=final_ts,
                    exit_price=fill.price,
                    reason=ExitReason.TIME_EXIT,
                )

        # Step 6: Compute Analytics and Compile Result
        daily_summaries = BacktestAnalytics.aggregate_daily_pnl(
            completed_trades=self.portfolio.completed_trades,
            equity_snapshots_by_date=self._equity_by_date,
            initial_capital=self.config.initial_capital,
        )

        avg_exposure = sum(self._exposure_samples) / len(self._exposure_samples) if self._exposure_samples else 0.0

        metrics = BacktestAnalytics.compute_metrics(
            initial_capital=self.config.initial_capital,
            completed_trades=self.portfolio.completed_trades,
            daily_snapshots=daily_summaries,
            equity_curve=self._equity_curve,
            total_turnover=self._total_turnover,
            peak_exposure=self._peak_exposure,
            average_exposure=avg_exposure,
            total_slippage=self._total_slippage,
        )

        return BacktestResult(
            config=self.config,
            metrics=metrics,
            daily_pnl=daily_summaries,
            completed_trades=list(self.portfolio.completed_trades),
            equity_curve=list(self._equity_curve),
            orders=self.simulator.get_all_orders(),
            execution_start_time=execution_start,
            execution_end_time=datetime.now(),
            aggregate_cost_report=self.simulator.get_aggregate_cost_report(total_slippage=self._total_slippage),
        )

    def _evaluate_strategy_for_symbol(
        self,
        symbol: str,
        candle: Candle,
        snapshot: IndicatorSnapshot,
        nifty_candle: Optional[Candle],
    ) -> None:
        """Evaluates pure strategy rules for a given instrument."""
        state = self._get_or_create_strategy_state(symbol)

        # Resolve ATR with graceful fallback during initial session warm-up
        atr_val = snapshot.atr_14
        coord = self.indicators._coordinators.get(symbol.upper().strip())
        if atr_val is None:
            if coord and coord.atr_calc._tr_history:
                atr_val = round(sum(coord.atr_calc._tr_history) / len(coord.atr_calc._tr_history), 4)
            else:
                atr_val = round(candle.range, 4)

        # Resolve Volume SMA with warm-up fallback
        vol_sma_val = snapshot.prev_avg_volume_10
        if vol_sma_val is None:
            if coord and coord.volume_sma_calc._history:
                vol_sma_val = round(sum(coord.volume_sma_calc._history) / len(coord.volume_sma_calc._history), 2)
            else:
                vol_sma_val = float(candle.volume)

        vol_ratio_val = snapshot.volume_surge_ratio
        if vol_ratio_val is None:
            vol_ratio_val = round(candle.volume / vol_sma_val, 4) if vol_sma_val > 0 else 1.0

        # Validate minimum required indicators
        if snapshot.vwap is None or atr_val is None or snapshot.orb_high is None or snapshot.orb_low is None:
            return

        market_input = StrategyMarketInput(
            candle=candle,
            stock_vwap=snapshot.vwap,
            atr=atr_val,
            opening_range_high=snapshot.orb_high,
            opening_range_low=snapshot.orb_low,
            volume_sma_10=vol_sma_val,
            volume_ratio=vol_ratio_val,
            market_regime=snapshot.nifty_regime,
            current_trading_session=TradingSessionStatus.OPEN,
            current_strategy_state=state,
            nifty_price=snapshot.nifty_close,
            nifty_vwap=snapshot.nifty_vwap,
            nifty_candle=nifty_candle,
        )

        # Evaluate strategy
        intent = self.strategy.evaluate(market_input)

        if intent is None:
            # If position is open, synchronize updated ratcheted trailing stop with simulator
            if state.position_status == PositionStatus.OPEN and state.active_trade is not None:
                self.simulator.update_stop_loss(
                    symbol=symbol,
                    new_stop=state.active_trade.current_stop,
                    timestamp=candle.timestamp,
                )
            return

        # Handle Exit Intent (e.g. VWAP Invalidation Exit)
        if intent.intent_type == "EXIT":
            pos = self.portfolio.get_position(symbol)
            if pos is not None and not pos.is_flat:
                fill = self.simulator.execute_market_exit(
                    symbol=symbol,
                    side=intent.side,
                    quantity=pos.quantity,
                    current_price=candle.close,
                    timestamp=candle.timestamp,
                    reason=intent.signal_reason,
                )
                self._total_turnover += (fill.price * fill.quantity)
            return

        # Handle Entry Intent
        if intent.intent_type == "ENTRY":
            # Circuit breaker check: if daily loss cap breached, abort new trades
            if self.portfolio.daily_risk_state.max_daily_loss_breached:
                state.position_status = PositionStatus.FLAT
                return

            # Risk Engine Evaluation
            balance = self.portfolio.get_account_balance()
            sector = self.config.sector_map.get(symbol, "GENERAL_EQUITY")
            sector_map = dict(self.config.sector_map)
            sector_map[symbol] = sector

            risk_context = RiskAssessmentContext(
                equity=balance.total_equity,
                available_cash=self.portfolio.available_cash,
                daily_realized_pnl=balance.total_realized_pnl,
                daily_unrealized_pnl=balance.total_unrealized_pnl,
                daily_executed_trades=self.portfolio.daily_risk_state.trades_executed_today,
                current_positions=self.portfolio.get_all_positions(),
                symbol_sector_map=sector_map,
                market_regime=snapshot.nifty_regime,
            )

            risk_decision = self.risk_engine.evaluate_from_intent(
                intent=intent,
                context=risk_context,
                sector=sector,
            )

            if risk_decision.is_approved and risk_decision.approved_quantity > 0:
                client_order_id = f"ORD_{symbol}_{candle.timestamp.strftime('%Y%m%d%H%M%S')}"

                order_req = OrderRequest(
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=intent.side,
                    order_type=intent.side.value,  # Placeholder, simulator enforces LIMIT
                    quantity=risk_decision.approved_quantity,
                    price=intent.proposed_entry_price,
                    trigger_price=intent.proposed_stop_price,
                    strategy_name="VWAP_ORB",
                    signal_id=f"SIG_{candle.timestamp.strftime('%Y%m%d%H%M%S')}",
                )

                # Store proposed stop price for when order fills
                self._pending_stop_prices[client_order_id] = intent.proposed_stop_price

                # Stage LIMIT order in simulator (to be tested on subsequent bars)
                self.simulator.submit_limit_order(
                    order_request=order_req,
                    timeout_bars=self.config.limit_timeout_bars,
                )
            else:
                # Risk rejected; revert position state to FLAT
                state.position_status = PositionStatus.FLAT
