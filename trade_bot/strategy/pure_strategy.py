"""
Pure Domain VWAP Pullback with ORB Confirmation Strategy.

Coordinates:
- Strategy Rules (LongEntryRule, ShortEntryRule)
- Exit Evaluation (ExitEvaluator)
- State Management (StrategyTradeState)
- Signal Construction (SignalBuilder)

Pure domain component: ZERO direct dependency on Upstox, REST, WebSockets, DB,
filesystem, logging, or environment variables.
"""

from __future__ import annotations

from typing import Optional

from trade_bot.domain.enums import MarketRegime, OrderSide
from trade_bot.strategy.entry_rules import (
    EntryEvaluationResult,
    LongEntryRule,
    ShortEntryRule,
)
from trade_bot.strategy.exit_rules import ExitEvaluator
from trade_bot.strategy.models import (
    SignalTriggerReason,
    StrategyMarketInput,
    TradeIntent,
    VwapOrbStrategyConfig,
)
from trade_bot.strategy.signal_builder import SignalBuilder
from trade_bot.strategy.state import PositionStatus


class VwapOrbPureStrategy:
    """
    Pure strategy domain component implementing the approved VWAP Pullback with ORB Confirmation.
    """

    VERSION = "1.0.0"

    def __init__(self, config: Optional[VwapOrbStrategyConfig] = None) -> None:
        self.config = config or VwapOrbStrategyConfig()
        self.long_rule = LongEntryRule(config=self.config)
        self.short_rule = ShortEntryRule(config=self.config)
        self.exit_evaluator = ExitEvaluator(
            trailing_atr_mult=self.config.trailing_stop_atr_mult,
            cutoff_time=self.config.window_end,
        )
        self.signal_builder = SignalBuilder()

    def evaluate_entry(self, market_input: StrategyMarketInput) -> EntryEvaluationResult:
        """
        Pure evaluation of entry conditions for a given market candle.
        Returns the detailed EntryEvaluationResult with checks and reasons.
        """
        if market_input.market_regime == MarketRegime.BULLISH:
            return self.long_rule.evaluate(market_input)
        elif market_input.market_regime == MarketRegime.BEARISH:
            return self.short_rule.evaluate(market_input)
        else:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.REGIME_MISMATCH,
                side=OrderSide.BUY,
                signal_price=market_input.candle.close,
                atr=market_input.atr,
                vwap=market_input.stock_vwap,
                or_high=market_input.opening_range_high,
                or_low=market_input.opening_range_low,
                volume_ratio=market_input.volume_ratio,
                criteria_checks={"regime": False},
            )

    def evaluate(self, market_input: StrategyMarketInput) -> Optional[TradeIntent]:
        """
        Evaluates candle input against strategy state and rules.
        Emits a typed TradeIntent for entries and exits, or None if no action is triggered.
        """
        state = market_input.current_strategy_state
        candle = market_input.candle
        instrument = market_input.get_instrument()

        # 1. Evaluate Exits for Open Positions
        if state.position_status == PositionStatus.OPEN and state.active_trade is not None:
            active_trade = state.active_trade
            exit_result = self.exit_evaluator.evaluate(
                candle=candle,
                active_trade=active_trade,
                stock_vwap=market_input.stock_vwap,
                atr=market_input.atr,
            )

            if exit_result.should_exit and exit_result.exit_price is not None and exit_result.reason is not None:
                # Opposite side to close the position
                exit_side = OrderSide.SELL if active_trade.side == OrderSide.BUY else OrderSide.BUY

                exit_intent = self.signal_builder.build_exit_intent(
                    strategy_version=self.VERSION,
                    timestamp=candle.timestamp,
                    instrument=instrument,
                    side=exit_side,
                    exit_price=exit_result.exit_price,
                    stop_price=exit_result.updated_stop,
                    atr=market_input.atr,
                    vwap=market_input.stock_vwap,
                    or_high=market_input.opening_range_high,
                    or_low=market_input.opening_range_low,
                    volume_ratio=market_input.volume_ratio,
                    exit_reason=exit_result.reason.value,
                    metadata={"trade_entry_price": active_trade.entry_price},
                )

                # Transition state to CLOSED/FLAT
                state.close_trade(
                    timestamp=candle.timestamp,
                    exit_price=exit_result.exit_price,
                    reason=exit_result.reason,
                )
                state.record_signal(exit_intent)
                return exit_intent

            else:
                # Position remains open: update watermarks and trailing stop level
                state.update_watermark(high=candle.high, low=candle.low)
                state.update_trailing_stop(exit_result.updated_stop)
                return None

        # 2. Evaluate Entries for Flat Positions
        elif state.position_status == PositionStatus.FLAT:
            can_enter, _ = state.can_enter()
            if not can_enter:
                return None

            entry_result = self.evaluate_entry(market_input)
            if (
                entry_result.is_valid
                and entry_result.proposed_entry_price is not None
                and entry_result.proposed_stop_price is not None
            ):
                entry_intent = self.signal_builder.build_entry_intent(
                    strategy_version=self.VERSION,
                    timestamp=candle.timestamp,
                    instrument=instrument,
                    side=entry_result.side,
                    signal_price=entry_result.signal_price,
                    proposed_entry_price=entry_result.proposed_entry_price,
                    proposed_stop_price=entry_result.proposed_stop_price,
                    atr=entry_result.atr,
                    vwap=entry_result.vwap,
                    or_high=entry_result.or_high,
                    or_low=entry_result.or_low,
                    volume_ratio=entry_result.volume_ratio,
                    signal_reason=entry_result.reason.value,
                    metadata={"criteria_checks": entry_result.criteria_checks},
                )

                if state.is_duplicate_signal(entry_intent):
                    return None

                state.record_signal(entry_intent)
                return entry_intent

        return None
