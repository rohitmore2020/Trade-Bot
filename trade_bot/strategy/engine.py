"""
VWAP-ORB Strategy Engine.

Pure, deterministic strategy engine for the VWAP Pullback with ORB Confirmation strategy.
Completely independent of broker APIs (Upstox/NSE).
Accepts market data (Candle + IndicatorSnapshot) and returns strongly typed VwapOrbSignal events.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Dict, List, Optional, Set
from trade_bot.domain.enums import MarketRegime, SignalDirection
from trade_bot.domain.models import Candle
from trade_bot.indicators.interfaces import IndicatorSnapshot
from trade_bot.strategy.models import (
    ActiveTradeState,
    UniverseCandidate,
    VwapOrbSignal,
    VwapOrbStrategyConfig,
)
from trade_bot.strategy.rules import (
    MarketRegimeRule,
    StopLossRule,
    TimeExitRule,
    TrailingStopRule,
    VwapExitRule,
)


class VWAPORBStrategyEngine:
    """
    Deterministic strategy engine implementing the approved VWAP-ORB rules.
    Maintains internal position tracking, trailing stops, watermarks, re-entry guards,
    and duplicate signal prevention.
    """

    STRATEGY_VERSION = "1.0.0"

    def __init__(
        self,
        config: Optional[VwapOrbStrategyConfig] = None,
        max_trades_per_symbol: int = 2,
    ) -> None:
        self.config = config or VwapOrbStrategyConfig()
        self.max_trades_per_symbol = max_trades_per_symbol

        # Active trade states: symbol -> ActiveTradeState
        self._active_trades: Dict[str, ActiveTradeState] = {}
        # Completed trades in current session
        self._closed_trades: List[ActiveTradeState] = []
        # Total executed fills/signals in session
        self._daily_trade_count: int = 0
        # Per-symbol trade count in session
        self._symbol_trade_counts: Dict[str, int] = {}
        # Cooldown: symbol -> timestamp of last exit
        self._last_exit_timestamps: Dict[str, datetime] = {}
        # Approved trading universe for the day
        self._eligible_universe: Set[str] = set()

    @property
    def active_positions_count(self) -> int:
        return len(self._active_trades)

    @property
    def daily_trade_count(self) -> int:
        return self._daily_trade_count

    @property
    def active_trades(self) -> Dict[str, ActiveTradeState]:
        return dict(self._active_trades)

    def is_symbol_in_active_trade(self, symbol: str) -> bool:
        return symbol.upper() in self._active_trades

    def set_eligible_universe(self, candidates: List[UniverseCandidate]) -> List[str]:
        """
        Filters and stores validated candidates meeting universe criteria:
        Turnover >= 100 Cr, ATR% in [1.5%, 6%], Price in [200, 5000], pre-market vol >= 10% OR gap >= 1%.
        """
        self._eligible_universe = {c.symbol.upper() for c in candidates if c.is_eligible}
        return sorted(list(self._eligible_universe))

    def reset_session(self) -> None:
        """Reset all intraday tracking state at session open (09:15 IST)."""
        self._active_trades.clear()
        self._closed_trades.clear()
        self._daily_trade_count = 0
        self._symbol_trade_counts.clear()
        self._last_exit_timestamps.clear()

    def process_candle(
        self,
        candle: Candle,
        snapshot: IndicatorSnapshot,
    ) -> Optional[VwapOrbSignal]:
        """
        Process a completed 5-minute candle and its indicator snapshot.
        Returns a VwapOrbSignal if an entry or exit condition is triggered, otherwise None.
        Strictly prevents look-ahead bias and duplicate signals.
        """
        symbol = candle.symbol.upper().strip()
        c_time = candle.timestamp.time()

        # ======================================================================
        # 1. EVALUATE EXITS FOR ACTIVE POSITIONS (VWAP Failure, SL, Trail, Time)
        # ======================================================================
        if symbol in self._active_trades:
            trade = self._active_trades[symbol]

            # A. Time Exit (at 14:30:00 IST cutoff)
            if TimeExitRule.should_exit(c_time, cutoff_time=self.config.window_end):
                return self._close_trade(
                    trade=trade,
                    exit_price=candle.close,
                    timestamp=candle.timestamp,
                    reason="TIME_EXIT",
                    snapshot=snapshot,
                )

            # B. VWAP Invalidation Exit
            if self.config.vwap_exit_enabled and snapshot.vwap is not None:
                if trade.direction == SignalDirection.LONG and VwapExitRule.should_exit_long(candle.close, snapshot.vwap):
                    return self._close_trade(
                        trade=trade,
                        exit_price=candle.close,
                        timestamp=candle.timestamp,
                        reason="VWAP_FAILURE",
                        snapshot=snapshot,
                    )
                elif trade.direction == SignalDirection.SHORT and VwapExitRule.should_exit_short(candle.close, snapshot.vwap):
                    return self._close_trade(
                        trade=trade,
                        exit_price=candle.close,
                        timestamp=candle.timestamp,
                        reason="VWAP_FAILURE",
                        snapshot=snapshot,
                    )

            # C. Trailing Stop & Initial Stop Loss Evaluation
            if snapshot.atr_14 is not None:
                if trade.direction == SignalDirection.LONG:
                    # Update peak watermark
                    trade.highest_price = max(trade.highest_price, candle.high)
                    # Ratchet trailing stop
                    new_stop = TrailingStopRule.update_long(
                        current_stop=trade.current_stop,
                        highest_price_since_entry=trade.highest_price,
                        atr=snapshot.atr_14,
                        multiplier=self.config.trailing_stop_atr_mult,
                    )
                    trade.current_stop = new_stop

                    # Check if bar breached stop price
                    if candle.low <= trade.current_stop:
                        reason = "TRAILING_STOP" if trade.current_stop > trade.initial_stop else "STOP_LOSS"
                        return self._close_trade(
                            trade=trade,
                            exit_price=trade.current_stop,
                            timestamp=candle.timestamp,
                            reason=reason,
                            snapshot=snapshot,
                        )

                elif trade.direction == SignalDirection.SHORT:
                    # Update trough watermark
                    trade.lowest_price = min(trade.lowest_price, candle.low)
                    # Ratchet trailing stop
                    new_stop = TrailingStopRule.update_short(
                        current_stop=trade.current_stop,
                        lowest_price_since_entry=trade.lowest_price,
                        atr=snapshot.atr_14,
                        multiplier=self.config.trailing_stop_atr_mult,
                    )
                    trade.current_stop = new_stop

                    # Check if bar breached stop price
                    if candle.high >= trade.current_stop:
                        reason = "TRAILING_STOP" if trade.current_stop < trade.initial_stop else "STOP_LOSS"
                        return self._close_trade(
                            trade=trade,
                            exit_price=trade.current_stop,
                            timestamp=candle.timestamp,
                            reason=reason,
                            snapshot=snapshot,
                        )

            # If position is still active, DO NOT emit a new entry signal (Duplicate Signal Prevention)
            return None

        # ======================================================================
        # 2. EVALUATE NEW ENTRIES (Re-entry Rules, Window, Regime, Strategy Setup)
        # ======================================================================

        # A. Trading Window (09:45 to 14:30 IST)
        if not (self.config.window_start <= c_time <= self.config.window_end):
            return None

        # B. Portfolio Risk Guardrails
        if self.active_positions_count >= self.config.max_open_positions:
            return None
        if self._daily_trade_count >= self.config.max_daily_trades:
            return None

        # C. Re-entry Rules
        symbol_trades = self._symbol_trade_counts.get(symbol, 0)
        if symbol_trades >= self.max_trades_per_symbol:
            return None

        # Cooldown check: Cannot re-enter on the exact same candle timestamp that exited
        last_exit = self._last_exit_timestamps.get(symbol)
        if last_exit is not None and candle.timestamp <= last_exit:
            return None

        # D. Data & Indicator Completeness
        if (
            snapshot.vwap is None
            or snapshot.atr_14 is None
            or snapshot.orb_high is None
            or snapshot.orb_low is None
            or not snapshot.orb_is_complete
            or snapshot.volume_surge_ratio is None
            or not snapshot.vix_is_acceptable
        ):
            return None

        # E. Market Regime Filtering (NIFTY VWAP)
        if snapshot.nifty_regime is None or snapshot.nifty_regime == MarketRegime.NEUTRAL:
            return None

        # F. Setup Verification
        # LONG ENTRY RULES:
        if snapshot.nifty_regime == MarketRegime.BULLISH:
            is_above_vwap = candle.close > snapshot.vwap
            is_pullback = candle.low <= round(snapshot.vwap * self.config.pullback_tolerance_long, 4)
            is_bullish_bar = candle.close > candle.open
            is_volume_surge = snapshot.volume_surge_ratio >= self.config.volume_surge_multiplier
            is_above_orb = candle.close > snapshot.orb_high

            if is_above_vwap and is_pullback and is_bullish_bar and is_volume_surge and is_above_orb:
                # Calculate entry limit and initial stop
                limit_entry = round(candle.close * (1.0 + self.config.limit_order_offset_pct), 2)
                initial_sl = round(limit_entry - (self.config.stop_loss_atr_mult * snapshot.atr_14), 2)

                signal = VwapOrbSignal(
                    timestamp=candle.timestamp,
                    symbol=symbol,
                    direction=SignalDirection.LONG,
                    signal_price=candle.close,
                    entry_price=limit_entry,
                    stop_price=initial_sl,
                    atr=snapshot.atr_14,
                    vwap=snapshot.vwap,
                    or_high=snapshot.orb_high,
                    or_low=snapshot.orb_low,
                    volume_ratio=snapshot.volume_surge_ratio,
                    reason="LONG_ENTRY",
                    strategy_version=self.STRATEGY_VERSION,
                )

                # Track active trade
                self._open_trade(
                    symbol=symbol,
                    direction=SignalDirection.LONG,
                    timestamp=candle.timestamp,
                    entry_price=limit_entry,
                    initial_stop=initial_sl,
                    candle_high=candle.high,
                    candle_low=candle.low,
                )
                return signal

        # SHORT ENTRY RULES:
        elif snapshot.nifty_regime == MarketRegime.BEARISH:
            is_below_vwap = candle.close < snapshot.vwap
            is_pullback = candle.high >= round(snapshot.vwap * self.config.pullback_tolerance_short, 4)
            is_bearish_bar = candle.close < candle.open
            is_volume_surge = snapshot.volume_surge_ratio >= self.config.volume_surge_multiplier
            is_below_orb = candle.close < snapshot.orb_low

            if is_below_vwap and is_pullback and is_bearish_bar and is_volume_surge and is_below_orb:
                # Calculate entry limit and initial stop
                limit_entry = round(candle.close * (1.0 - self.config.limit_order_offset_pct), 2)
                initial_sl = round(limit_entry + (self.config.stop_loss_atr_mult * snapshot.atr_14), 2)

                signal = VwapOrbSignal(
                    timestamp=candle.timestamp,
                    symbol=symbol,
                    direction=SignalDirection.SHORT,
                    signal_price=candle.close,
                    entry_price=limit_entry,
                    stop_price=initial_sl,
                    atr=snapshot.atr_14,
                    vwap=snapshot.vwap,
                    or_high=snapshot.orb_high,
                    or_low=snapshot.orb_low,
                    volume_ratio=snapshot.volume_surge_ratio,
                    reason="SHORT_ENTRY",
                    strategy_version=self.STRATEGY_VERSION,
                )

                # Track active trade
                self._open_trade(
                    symbol=symbol,
                    direction=SignalDirection.SHORT,
                    timestamp=candle.timestamp,
                    entry_price=limit_entry,
                    initial_stop=initial_sl,
                    candle_high=candle.high,
                    candle_low=candle.low,
                )
                return signal

        return None

    def _open_trade(
        self,
        symbol: str,
        direction: SignalDirection,
        timestamp: datetime,
        entry_price: float,
        initial_stop: float,
        candle_high: float,
        candle_low: float,
    ) -> None:
        self._active_trades[symbol] = ActiveTradeState(
            symbol=symbol,
            direction=direction,
            entry_timestamp=timestamp,
            entry_price=entry_price,
            initial_stop=initial_stop,
            current_stop=initial_stop,
            highest_price=candle_high,
            lowest_price=candle_low,
            status="OPEN",
        )
        self._daily_trade_count += 1
        self._symbol_trade_counts[symbol] = self._symbol_trade_counts.get(symbol, 0) + 1

    def _close_trade(
        self,
        trade: ActiveTradeState,
        exit_price: float,
        timestamp: datetime,
        reason: str,
        snapshot: IndicatorSnapshot,
    ) -> VwapOrbSignal:
        trade.status = "CLOSED"
        trade.exit_timestamp = timestamp
        trade.exit_price = exit_price
        trade.exit_reason = reason

        self._active_trades.pop(trade.symbol, None)
        self._closed_trades.append(trade)
        self._last_exit_timestamps[trade.symbol] = timestamp

        # Emit exit signal
        return VwapOrbSignal(
            timestamp=timestamp,
            symbol=trade.symbol,
            direction=SignalDirection.FLAT,
            signal_price=exit_price,
            entry_price=exit_price,
            stop_price=trade.current_stop,
            atr=snapshot.atr_14 if snapshot.atr_14 is not None else 0.0,
            vwap=snapshot.vwap if snapshot.vwap is not None else 0.0,
            or_high=snapshot.orb_high if snapshot.orb_high is not None else 0.0,
            or_low=snapshot.orb_low if snapshot.orb_low is not None else 0.0,
            volume_ratio=snapshot.volume_surge_ratio if snapshot.volume_surge_ratio is not None else 0.0,
            reason=reason,
            strategy_version=self.STRATEGY_VERSION,
            metadata={"initial_entry_price": trade.entry_price, "exit_reason": reason},
        )
