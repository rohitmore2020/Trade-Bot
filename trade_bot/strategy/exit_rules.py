"""
Deterministic Exit Evaluation Rules for VWAP Pullback with ORB Confirmation.

Implements approved exits:
1. Initial Stop Loss
2. ATR Trailing Stop (never moves in unfavorable direction)
3. VWAP Failure Exit
4. 14:30:00 IST Mandatory Time Exit

Zero external infrastructure dependencies; pure domain logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Optional

from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import Candle
from trade_bot.strategy.state import ActiveTradeState, ExitReason


@dataclass(frozen=True, slots=True)
class ExitEvaluationResult:
    """Result of exit rule evaluation on an active trade."""
    should_exit: bool
    reason: Optional[ExitReason]
    exit_price: Optional[float]
    updated_stop: float


class TimeExitEvaluator:
    """Mandatory exit at 14:30:00 IST."""

    @staticmethod
    def should_exit(current_time: time, cutoff_time: time = time(14, 30, 0)) -> bool:
        return current_time >= cutoff_time

    @staticmethod
    def evaluate(candle: Candle, cutoff_time: time = time(14, 30, 0)) -> Optional[ExitEvaluationResult]:
        if TimeExitEvaluator.should_exit(candle.timestamp.time(), cutoff_time):
            return ExitEvaluationResult(
                should_exit=True,
                reason=ExitReason.TIME_EXIT,
                exit_price=candle.close,
                updated_stop=0.0,
            )
        return None


class VwapExitEvaluator:
    """Detects invalidation when price crosses VWAP against position."""

    @staticmethod
    def should_exit_long(close_price: float, vwap: float) -> bool:
        return close_price < vwap

    @staticmethod
    def should_exit_short(close_price: float, vwap: float) -> bool:
        return close_price > vwap

    @staticmethod
    def evaluate(candle: Candle, active_trade: ActiveTradeState, vwap: float) -> Optional[ExitEvaluationResult]:
        if active_trade.side == OrderSide.BUY and VwapExitEvaluator.should_exit_long(candle.close, vwap):
            return ExitEvaluationResult(
                should_exit=True,
                reason=ExitReason.VWAP_FAILURE,
                exit_price=candle.close,
                updated_stop=active_trade.current_stop,
            )
        elif active_trade.side == OrderSide.SELL and VwapExitEvaluator.should_exit_short(candle.close, vwap):
            return ExitEvaluationResult(
                should_exit=True,
                reason=ExitReason.VWAP_FAILURE,
                exit_price=candle.close,
                updated_stop=active_trade.current_stop,
            )
        return None


class InitialStopEvaluator:
    """Evaluates if price breached the initial stop loss price."""

    @staticmethod
    def evaluate(candle: Candle, active_trade: ActiveTradeState) -> Optional[ExitEvaluationResult]:
        if active_trade.side == OrderSide.BUY:
            if candle.low <= active_trade.initial_stop:
                exit_px = min(candle.open, active_trade.initial_stop)
                return ExitEvaluationResult(
                    should_exit=True,
                    reason=ExitReason.INITIAL_STOP,
                    exit_price=exit_px,
                    updated_stop=active_trade.initial_stop,
                )
        elif active_trade.side == OrderSide.SELL:
            if candle.high >= active_trade.initial_stop:
                exit_px = max(candle.open, active_trade.initial_stop)
                return ExitEvaluationResult(
                    should_exit=True,
                    reason=ExitReason.INITIAL_STOP,
                    exit_price=exit_px,
                    updated_stop=active_trade.initial_stop,
                )
        return None


class TrailingStopEvaluator:
    """
    Ratchets trailing stop at 2.0 * ATR from peak (Long) or trough (Short).
    Never retreats in an unfavorable direction.
    """

    @staticmethod
    def calculate_long_stop(current_stop: float, peak_price: float, atr: float, multiplier: float = 2.0) -> float:
        trail_level = round(peak_price - (multiplier * atr), 2)
        return max(current_stop, trail_level)

    @staticmethod
    def calculate_short_stop(current_stop: float, trough_price: float, atr: float, multiplier: float = 2.0) -> float:
        trail_level = round(trough_price + (multiplier * atr), 2)
        return min(current_stop, trail_level)

    @staticmethod
    def evaluate(
        candle: Candle,
        active_trade: ActiveTradeState,
        atr: float,
        multiplier: float = 2.0,
    ) -> ExitEvaluationResult:
        if active_trade.side == OrderSide.BUY:
            new_peak = max(active_trade.highest_price, candle.high)
            new_stop = TrailingStopEvaluator.calculate_long_stop(
                current_stop=active_trade.current_stop,
                peak_price=new_peak,
                atr=atr,
                multiplier=multiplier,
            )
            if candle.low <= new_stop:
                exit_px = min(candle.open, new_stop)
                reason = ExitReason.TRAILING_STOP if new_stop > active_trade.initial_stop else ExitReason.INITIAL_STOP
                return ExitEvaluationResult(
                    should_exit=True,
                    reason=reason,
                    exit_price=exit_px,
                    updated_stop=new_stop,
                )
            return ExitEvaluationResult(
                should_exit=False,
                reason=None,
                exit_price=None,
                updated_stop=new_stop,
            )
        else:  # SELL
            new_trough = min(active_trade.lowest_price, candle.low)
            new_stop = TrailingStopEvaluator.calculate_short_stop(
                current_stop=active_trade.current_stop,
                trough_price=new_trough,
                atr=atr,
                multiplier=multiplier,
            )
            if candle.high >= new_stop:
                exit_px = max(candle.open, new_stop)
                reason = ExitReason.TRAILING_STOP if new_stop < active_trade.initial_stop else ExitReason.INITIAL_STOP
                return ExitEvaluationResult(
                    should_exit=True,
                    reason=reason,
                    exit_price=exit_px,
                    updated_stop=new_stop,
                )
            return ExitEvaluationResult(
                should_exit=False,
                reason=None,
                exit_price=None,
                updated_stop=new_stop,
            )


class ExitEvaluator:
    """
    Coordinating exit evaluator checking all exit conditions in prioritized order:
    1. Time exit (>= 14:30:00 IST)
    2. VWAP invalidation exit
    3. Stop loss / Trailing stop exit
    """

    def __init__(self, trailing_atr_mult: float = 2.0, cutoff_time: time = time(14, 30, 0)) -> None:
        self.trailing_atr_mult = trailing_atr_mult
        self.cutoff_time = cutoff_time

    def evaluate(
        self,
        candle: Candle,
        active_trade: ActiveTradeState,
        stock_vwap: float,
        atr: float,
    ) -> ExitEvaluationResult:
        # 1. Time Exit
        time_res = TimeExitEvaluator.evaluate(candle, cutoff_time=self.cutoff_time)
        if time_res and time_res.should_exit:
            return ExitEvaluationResult(
                should_exit=True,
                reason=time_res.reason,
                exit_price=time_res.exit_price,
                updated_stop=active_trade.current_stop,
            )

        # 2. VWAP Invalidation Exit
        vwap_res = VwapExitEvaluator.evaluate(candle, active_trade, vwap=stock_vwap)
        if vwap_res and vwap_res.should_exit:
            return ExitEvaluationResult(
                should_exit=True,
                reason=vwap_res.reason,
                exit_price=vwap_res.exit_price,
                updated_stop=active_trade.current_stop,
            )

        # 3. Trailing Stop / Initial Stop Evaluation
        trail_res = TrailingStopEvaluator.evaluate(
            candle=candle,
            active_trade=active_trade,
            atr=atr,
            multiplier=self.trailing_atr_mult,
        )
        return trail_res
