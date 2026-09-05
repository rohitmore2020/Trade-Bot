"""
Pure Deterministic Entry Rules for VWAP Pullback with ORB Confirmation.

Implements exact, symmetrical Long and Short entry conditions:
1. Operational Window (09:45:00 - 14:30:00 IST)
2. Macro Regime (NIFTY vs NIFTY VWAP)
3. Stock Price vs Stock VWAP
4. Pullback to VWAP (<= 1.002 for Long, >= 0.998 for Short)
5. Candle Directional Confirmation (Bullish close for Long, Bearish close for Short)
6. Intraday Volume Surge (>= 1.5x 10-bar SMA Volume)
7. Opening Range Breakout Confirmation (> OR High for Long, < OR Low for Short)

Zero external infrastructure dependencies; pure business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Dict, Optional

from trade_bot.domain.enums import MarketRegime, OrderSide
from trade_bot.strategy.models import (
    SignalTriggerReason,
    StrategyMarketInput,
    VwapOrbStrategyConfig,
)


@dataclass(frozen=True, slots=True)
class EntryEvaluationResult:
    """Deterministic result of evaluating entry rules on a market candle."""
    is_valid: bool
    reason: SignalTriggerReason
    side: OrderSide
    signal_price: float
    proposed_entry_price: Optional[float] = None
    proposed_stop_price: Optional[float] = None
    atr: float = 0.0
    vwap: float = 0.0
    or_high: float = 0.0
    or_low: float = 0.0
    volume_ratio: float = 0.0
    criteria_checks: Dict[str, bool] = field(default_factory=dict)


class LongEntryRule:
    """
    Evaluates Long entry conditions for VWAP Pullback with ORB Confirmation.
    """

    def __init__(self, config: Optional[VwapOrbStrategyConfig] = None) -> None:
        self.config = config or VwapOrbStrategyConfig()

    def is_within_window(self, current_time: time) -> bool:
        """Trading allowed only within 09:45:00 to 14:30:00 IST."""
        return self.config.window_start <= current_time <= self.config.window_end

    def evaluate(self, market_input: StrategyMarketInput) -> EntryEvaluationResult:
        candle = market_input.candle
        c_time = candle.timestamp.time()
        stock_vwap = market_input.stock_vwap
        or_high = market_input.opening_range_high
        or_low = market_input.opening_range_low
        atr = market_input.atr
        vol_sma = market_input.volume_sma_10

        vol_ratio = market_input.volume_ratio if market_input.volume_ratio > 0 else (
            (candle.volume / vol_sma) if vol_sma > 0 else 0.0
        )
        vol_threshold = round(self.config.volume_surge_multiplier * vol_sma, 4)
        pullback_threshold = round(stock_vwap * self.config.pullback_tolerance_long, 4)

        checks: Dict[str, bool] = {
            "window": self.is_within_window(c_time),
            "regime": market_input.market_regime == MarketRegime.BULLISH,
            "close_above_vwap": candle.close > stock_vwap,
            "pullback": candle.low <= pullback_threshold,
            "bullish_close": candle.close > candle.open,
            "volume_surge": candle.volume >= vol_threshold or vol_ratio >= self.config.volume_surge_multiplier,
            "above_orb_high": candle.close > or_high,
        }

        # Priority 1: Window
        if not checks["window"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.OUTSIDE_TRADING_WINDOW,
                side=OrderSide.BUY,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 2: Regime
        if not checks["regime"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.REGIME_MISMATCH,
                side=OrderSide.BUY,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 3: VWAP Position
        if not checks["close_above_vwap"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.VWAP_REJECTION,
                side=OrderSide.BUY,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 4: Pullback
        if not checks["pullback"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.PULLBACK_REJECTION,
                side=OrderSide.BUY,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 5: Bullish Close
        if not checks["bullish_close"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.NOT_BULLISH_CANDLE,
                side=OrderSide.BUY,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 6: Volume Surge
        if not checks["volume_surge"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.VOLUME_REJECTION,
                side=OrderSide.BUY,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 7: ORB High Breakout
        if not checks["above_orb_high"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.ORB_REJECTION,
                side=OrderSide.BUY,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # All criteria satisfied: Calculate entry and stop
        limit_entry = round(candle.close * (1.0 + self.config.limit_order_offset_pct), 2)
        initial_sl = round(limit_entry - (self.config.stop_loss_atr_mult * atr), 2)

        return EntryEvaluationResult(
            is_valid=True,
            reason=SignalTriggerReason.LONG_ENTRY,
            side=OrderSide.BUY,
            signal_price=candle.close,
            proposed_entry_price=limit_entry,
            proposed_stop_price=initial_sl,
            atr=atr,
            vwap=stock_vwap,
            or_high=or_high,
            or_low=or_low,
            volume_ratio=vol_ratio,
            criteria_checks=checks,
        )


class ShortEntryRule:
    """
    Evaluates Short entry conditions for VWAP Pullback with ORB Confirmation.
    Exact symmetrical mirror of LongEntryRule.
    """

    def __init__(self, config: Optional[VwapOrbStrategyConfig] = None) -> None:
        self.config = config or VwapOrbStrategyConfig()

    def is_within_window(self, current_time: time) -> bool:
        """Trading allowed only within 09:45:00 to 14:30:00 IST."""
        return self.config.window_start <= current_time <= self.config.window_end

    def evaluate(self, market_input: StrategyMarketInput) -> EntryEvaluationResult:
        candle = market_input.candle
        c_time = candle.timestamp.time()
        stock_vwap = market_input.stock_vwap
        or_high = market_input.opening_range_high
        or_low = market_input.opening_range_low
        atr = market_input.atr
        vol_sma = market_input.volume_sma_10

        vol_ratio = market_input.volume_ratio if market_input.volume_ratio > 0 else (
            (candle.volume / vol_sma) if vol_sma > 0 else 0.0
        )
        vol_threshold = round(self.config.volume_surge_multiplier * vol_sma, 4)
        pullback_threshold = round(stock_vwap * self.config.pullback_tolerance_short, 4)

        checks: Dict[str, bool] = {
            "window": self.is_within_window(c_time),
            "regime": market_input.market_regime == MarketRegime.BEARISH,
            "close_below_vwap": candle.close < stock_vwap,
            "pullback": candle.high >= pullback_threshold,
            "bearish_close": candle.close < candle.open,
            "volume_surge": candle.volume >= vol_threshold or vol_ratio >= self.config.volume_surge_multiplier,
            "below_orb_low": candle.close < or_low,
        }

        # Priority 1: Window
        if not checks["window"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.OUTSIDE_TRADING_WINDOW,
                side=OrderSide.SELL,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 2: Regime
        if not checks["regime"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.REGIME_MISMATCH,
                side=OrderSide.SELL,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 3: VWAP Position
        if not checks["close_below_vwap"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.VWAP_REJECTION,
                side=OrderSide.SELL,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 4: Pullback
        if not checks["pullback"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.PULLBACK_REJECTION,
                side=OrderSide.SELL,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 5: Bearish Close
        if not checks["bearish_close"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.NOT_BEARISH_CANDLE,
                side=OrderSide.SELL,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 6: Volume Surge
        if not checks["volume_surge"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.VOLUME_REJECTION,
                side=OrderSide.SELL,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # Priority 7: ORB Low Breakdown
        if not checks["below_orb_low"]:
            return EntryEvaluationResult(
                is_valid=False,
                reason=SignalTriggerReason.ORB_REJECTION,
                side=OrderSide.SELL,
                signal_price=candle.close,
                atr=atr,
                vwap=stock_vwap,
                or_high=or_high,
                or_low=or_low,
                volume_ratio=vol_ratio,
                criteria_checks=checks,
            )

        # All criteria satisfied: Calculate entry and stop
        limit_entry = round(candle.close * (1.0 - self.config.limit_order_offset_pct), 2)
        initial_sl = round(limit_entry + (self.config.stop_loss_atr_mult * atr), 2)

        return EntryEvaluationResult(
            is_valid=True,
            reason=SignalTriggerReason.SHORT_ENTRY,
            side=OrderSide.SELL,
            signal_price=candle.close,
            proposed_entry_price=limit_entry,
            proposed_stop_price=initial_sl,
            atr=atr,
            vwap=stock_vwap,
            or_high=or_high,
            or_low=or_low,
            volume_ratio=vol_ratio,
            criteria_checks=checks,
        )
