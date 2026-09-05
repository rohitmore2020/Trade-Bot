"""
VWAP-ORB Deterministic Strategy Rules.

Pure, machine-executable rule implementations strictly reflecting the VWAP-ORB specification.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Dict, List, Optional
from trade_bot.domain.enums import OrderSide, SignalDirection
from trade_bot.domain.models import Candle, Signal
from trade_bot.indicators.orb import ORBLevels
from trade_bot.strategy.models import (
    MarketRegime,
    PositionSizingResult,
    SignalEvaluationResult,
    SignalTriggerReason,
    VwapOrbStrategyConfig,
)


class MarketRegimeRule:
    """Evaluates the macro market regime from NIFTY index and its VWAP."""

    @staticmethod
    def evaluate(nifty_price: float, nifty_vwap: float) -> MarketRegime:
        if nifty_price > nifty_vwap:
            return MarketRegime.BULLISH
        elif nifty_price < nifty_vwap:
            return MarketRegime.BEARISH
        return MarketRegime.NEUTRAL


class VwapOrbSignalRule:
    """
    Evaluates candle and indicator state against VWAP-ORB entry criteria.
    """

    def __init__(self, config: Optional[VwapOrbStrategyConfig] = None) -> None:
        self.config = config or VwapOrbStrategyConfig()

    def is_within_trading_window(self, current_time: time) -> bool:
        """Trading allowed only within 09:45:00 to 14:30:00 IST."""
        return self.config.window_start <= current_time <= self.config.window_end

    def evaluate_long(
        self,
        candle: Candle,
        stock_vwap: float,
        orb_levels: ORBLevels,
        volume_sma_10: float,
        regime: MarketRegime,
        atr_14: float,
    ) -> SignalEvaluationResult:
        """
        Evaluate Long entry conditions:
        1. Trading window: 09:45 - 14:30
        2. Regime: NIFTY > VWAP (BULLISH)
        3. Close > VWAP
        4. Pullback: Low <= VWAP * 1.002
        5. Bullish close: Close > Open
        6. Volume >= 1.5 * 10-bar SMA Volume
        7. Price > OR High
        """
        c_time = candle.timestamp.time()
        checks: Dict[str, bool] = {
            "window": self.is_within_trading_window(c_time),
            "regime": regime == MarketRegime.BULLISH,
            "close_above_vwap": candle.close > stock_vwap,
            "pullback": candle.low <= round(stock_vwap * self.config.pullback_tolerance_long, 4),
            "bullish_close": candle.close > candle.open,
            "volume_surge": candle.volume >= (self.config.volume_surge_multiplier * volume_sma_10),
            "above_orb_high": candle.close > orb_levels.high,
        }

        if not checks["window"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.OUTSIDE_TRADING_WINDOW,
                criteria_checks=checks,
            )

        if not checks["regime"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.REGIME_MISMATCH,
                criteria_checks=checks,
            )

        if not checks["pullback"] or not checks["close_above_vwap"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.NO_PULLBACK,
                criteria_checks=checks,
            )

        if not checks["bullish_close"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.NOT_BULLISH_CANDLE,
                criteria_checks=checks,
            )

        if not checks["volume_surge"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.VOLUME_SURGE_UNMET,
                criteria_checks=checks,
            )

        if not checks["above_orb_high"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.ORB_CONDITION_UNMET,
                criteria_checks=checks,
            )

        # All conditions satisfied: Place LIMIT BUY at Close + 0.05%
        limit_entry = round(candle.close * (1.0 + self.config.limit_order_offset_pct), 2)
        initial_sl = round(limit_entry - (self.config.stop_loss_atr_mult * atr_14), 2)

        return SignalEvaluationResult(
            symbol=candle.symbol,
            timestamp=candle.timestamp,
            is_signal=True,
            trigger_reason=SignalTriggerReason.LONG_ENTRY,
            limit_entry_price=limit_entry,
            initial_stop_price=initial_sl,
            atr_value=atr_14,
            criteria_checks=checks,
        )

    def evaluate_short(
        self,
        candle: Candle,
        stock_vwap: float,
        orb_levels: ORBLevels,
        volume_sma_10: float,
        regime: MarketRegime,
        atr_14: float,
    ) -> SignalEvaluationResult:
        """
        Evaluate Short entry conditions:
        1. Trading window: 09:45 - 14:30
        2. Regime: NIFTY < VWAP (BEARISH)
        3. Close < VWAP
        4. Pullback: High >= VWAP * 0.998
        5. Bearish close: Close < Open
        6. Volume >= 1.5 * 10-bar SMA Volume
        7. Price < OR Low
        """
        c_time = candle.timestamp.time()
        checks: Dict[str, bool] = {
            "window": self.is_within_trading_window(c_time),
            "regime": regime == MarketRegime.BEARISH,
            "close_below_vwap": candle.close < stock_vwap,
            "pullback": candle.high >= round(stock_vwap * self.config.pullback_tolerance_short, 4),
            "bearish_close": candle.close < candle.open,
            "volume_surge": candle.volume >= (self.config.volume_surge_multiplier * volume_sma_10),
            "below_orb_low": candle.close < orb_levels.low,
        }

        if not checks["window"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.OUTSIDE_TRADING_WINDOW,
                criteria_checks=checks,
            )

        if not checks["regime"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.REGIME_MISMATCH,
                criteria_checks=checks,
            )

        if not checks["pullback"] or not checks["close_below_vwap"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.NO_PULLBACK,
                criteria_checks=checks,
            )

        if not checks["bearish_close"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.NOT_BEARISH_CANDLE,
                criteria_checks=checks,
            )

        if not checks["volume_surge"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.VOLUME_SURGE_UNMET,
                criteria_checks=checks,
            )

        if not checks["below_orb_low"]:
            return SignalEvaluationResult(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                is_signal=False,
                trigger_reason=SignalTriggerReason.ORB_CONDITION_UNMET,
                criteria_checks=checks,
            )

        # Place LIMIT SELL at Close - 0.05%
        limit_entry = round(candle.close * (1.0 - self.config.limit_order_offset_pct), 2)
        initial_sl = round(limit_entry + (self.config.stop_loss_atr_mult * atr_14), 2)

        return SignalEvaluationResult(
            symbol=candle.symbol,
            timestamp=candle.timestamp,
            is_signal=True,
            trigger_reason=SignalTriggerReason.SHORT_ENTRY,
            limit_entry_price=limit_entry,
            initial_stop_price=initial_sl,
            atr_value=atr_14,
            criteria_checks=checks,
        )


class StopLossRule:
    """Calculates deterministic initial stop-loss price."""

    @staticmethod
    def calculate(side: OrderSide, entry_price: float, atr: float, multiplier: float = 1.5) -> float:
        distance = round(multiplier * atr, 2)
        if side == OrderSide.BUY:
            return round(entry_price - distance, 2)
        return round(entry_price + distance, 2)


class TrailingStopRule:
    """
    Ratchets trailing stop at 2.0 * ATR from highest peak (Long) or lowest trough (Short).
    Never retreats adverse to the position.
    """

    @staticmethod
    def update_long(current_stop: float, highest_price_since_entry: float, atr: float, multiplier: float = 2.0) -> float:
        trail_level = round(highest_price_since_entry - (multiplier * atr), 2)
        return max(current_stop, trail_level)

    @staticmethod
    def update_short(current_stop: float, lowest_price_since_entry: float, atr: float, multiplier: float = 2.0) -> float:
        trail_level = round(lowest_price_since_entry + (multiplier * atr), 2)
        return min(current_stop, trail_level)


class VwapExitRule:
    """Detects invalidation when price crosses VWAP against position."""

    @staticmethod
    def should_exit_long(current_price: float, vwap: float) -> bool:
        return current_price < vwap

    @staticmethod
    def should_exit_short(current_price: float, vwap: float) -> bool:
        return current_price > vwap


class TimeExitRule:
    """Mandatory exit at 14:30:00 IST."""

    @staticmethod
    def should_exit(current_time: time, cutoff_time: time = time(14, 30, 0)) -> bool:
        return current_time >= cutoff_time


class PositionSizer:
    """
    Calculates exact integer quantity using 0.5% risk budget and 20% max capital cap.
    """

    @staticmethod
    def calculate(
        equity: float,
        entry_price: float,
        stop_price: float,
        risk_pct: float = 0.005,  # 0.5%
        max_capital_pct: float = 0.20,  # 20%
    ) -> PositionSizingResult:
        if equity <= 0 or entry_price <= 0 or stop_price <= 0:
            return PositionSizingResult(0, entry_price, stop_price, 0.0, 0.0, 0.0, False)

        risk_per_share = round(abs(entry_price - stop_price), 4)
        if risk_per_share == 0:
            return PositionSizingResult(0, entry_price, stop_price, 0.0, 0.0, 0.0, False)

        risk_budget = equity * risk_pct
        qty_risk = int(risk_budget / risk_per_share)

        max_notional = equity * max_capital_pct
        qty_capital = int(max_notional / entry_price)

        final_qty = min(qty_risk, qty_capital)
        is_capped = qty_capital < qty_risk

        notional_val = round(final_qty * entry_price, 2)
        total_risk = round(final_qty * risk_per_share, 2)

        return PositionSizingResult(
            quantity=max(0, final_qty),
            entry_price=entry_price,
            stop_price=stop_price,
            risk_per_share=risk_per_share,
            total_risk_amount=total_risk,
            notional_value=notional_val,
            is_capital_capped=is_capped,
        )


class SessionRiskGuard:
    """Enforces session constraints: max 3 positions, max 6 trades, 2% daily loss."""

    @staticmethod
    def can_open_position(
        current_open_positions: int,
        daily_executed_trades: int,
        daily_loss_pct: float,
        max_positions: int = 3,
        max_trades: int = 6,
        max_loss_pct: float = 0.02,
    ) -> tuple[bool, Optional[str]]:
        if daily_loss_pct >= max_loss_pct:
            return False, f"Daily loss cap breached: {daily_loss_pct * 100:.2f}% >= {max_loss_pct * 100:.2f}%"
        if current_open_positions >= max_positions:
            return False, f"Maximum open positions reached: {current_open_positions} >= {max_positions}"
        if daily_executed_trades >= max_trades:
            return False, f"Maximum daily trades executed: {daily_executed_trades} >= {max_trades}"
        return True, None
