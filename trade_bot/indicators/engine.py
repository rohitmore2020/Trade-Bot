"""
VWAP-ORB Indicator Engine.

Pure business-logic indicator engine orchestrating all deterministic indicators
required by the approved VWAP-ORB strategy for Indian NSE equities.
Zero dependencies on brokers, HTTP, WebSockets, databases, or environment variables.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Dict, List, Optional
from trade_bot.domain.enums import MarketRegime
from trade_bot.domain.models import Candle, Tick
from trade_bot.indicators.coordinator import StockIndicatorCoordinator
from trade_bot.indicators.exceptions import (
    IndicatorValidationError,
    LookAheadViolationError,
)
from trade_bot.indicators.interfaces import IndicatorSnapshot, MarketDataInput
from trade_bot.indicators.nifty_regime import NiftyRegimeIndicator
from trade_bot.indicators.vix_filter import IndiaVIXFilter, VIXRegime


class IndicatorEngine:
    """
    Central deterministic indicator engine for the VWAP-ORB strategy.
    
    Orchestrates per-symbol calculators (VWAP, ATR-14, ORB, Volume SMA, Gap %)
    and market-wide indicators (NIFTY session VWAP, Market Regime, India VIX filter).
    
    Guarantees strict zero look-ahead bias, chronological integrity, and
    seamless multi-session boundary transitions.
    """

    def __init__(
        self,
        atr_period: int = 14,
        volume_sma_period: int = 10,
        min_gap_pct: float = 1.0,
        orb_start: time = time(9, 15, 0),
        orb_end: time = time(9, 30, 0),
        vix_min: float = 10.0,
        vix_max: float = 24.0,
        vix_extreme: float = 28.0,
    ) -> None:
        self.atr_period = atr_period
        self.volume_sma_period = volume_sma_period
        self.min_gap_pct = min_gap_pct
        self.orb_start = orb_start
        self.orb_end = orb_end

        # Market-wide context indicators
        self.nifty_indicator = NiftyRegimeIndicator(symbol="^NSEI")
        self.vix_filter = IndiaVIXFilter(
            min_vix=vix_min,
            max_vix=vix_max,
            extreme_vix=vix_extreme,
        )

        # Per-symbol state coordinators: symbol -> StockIndicatorCoordinator
        self._coordinators: Dict[str, StockIndicatorCoordinator] = {}

        # Session tracking state
        self._current_session_date: Optional[date] = None
        self._last_completed_timestamps: Dict[str, datetime] = {}
        self._latest_snapshots: Dict[str, IndicatorSnapshot] = {}
        self._latest_close_by_symbol: Dict[str, float] = {}

    @property
    def registered_symbols(self) -> List[str]:
        return sorted(list(self._coordinators.keys()))

    def _get_or_create_coordinator(self, symbol: str) -> StockIndicatorCoordinator:
        sym = symbol.upper().strip()
        if sym not in self._coordinators:
            coord = StockIndicatorCoordinator(
                symbol=sym,
                atr_period=self.atr_period,
                volume_sma_period=self.volume_sma_period,
                min_gap_pct=self.min_gap_pct,
            )
            # If we know previous close for this symbol, seed it
            if sym in self._latest_close_by_symbol:
                coord.set_previous_day_close(self._latest_close_by_symbol[sym])
            self._coordinators[sym] = coord
        return self._coordinators[sym]

    def _validate_candle(self, candle: Candle) -> None:
        """Enforce mathematical and physical invariants on candle data."""
        if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0:
            raise IndicatorValidationError(
                f"Candle OHLC prices must be strictly positive: {candle}"
            )
        if candle.high < candle.low:
            raise IndicatorValidationError(
                f"Candle High ({candle.high}) cannot be less than Low ({candle.low})"
            )
        if candle.high < max(candle.open, candle.close):
            raise IndicatorValidationError(
                f"Candle High ({candle.high}) lower than Open/Close ({candle.open}, {candle.close})"
            )
        if candle.low > min(candle.open, candle.close):
            raise IndicatorValidationError(
                f"Candle Low ({candle.low}) higher than Open/Close ({candle.open}, {candle.close})"
            )
        if candle.volume < 0:
            raise IndicatorValidationError(
                f"Candle volume cannot be negative: {candle.volume}"
            )

    def _check_session_transition(self, candle_date: date) -> None:
        """
        Detects transition to a new trading day.
        Automatically performs session reset:
        - Resets daily VWAP and ORB.
        - Stores previous session's close to evaluate morning overnight gap and gap True Range.
        - Preserves multi-day rolling ATR and Volume history.
        """
        if self._current_session_date is None:
            self._current_session_date = candle_date
            return

        if candle_date > self._current_session_date:
            # Transition to next trading day
            self._current_session_date = candle_date
            self.nifty_indicator.reset()

            for sym, coord in self._coordinators.items():
                prev_close = self._latest_close_by_symbol.get(sym)
                coord.start_new_session(prev_day_close=prev_close)

    def process(self, input_data: MarketDataInput) -> IndicatorSnapshot:
        """
        Primary engine entrypoint. Ingests strongly typed MarketDataInput and
        returns an immutable IndicatorSnapshot.
        """
        return self.process_candle(
            candle=input_data.candle,
            is_forming=input_data.is_forming,
            nifty_candle=input_data.nifty_candle,
            india_vix=input_data.india_vix,
        )

    def process_candle(
        self,
        candle: Candle,
        is_forming: bool = False,
        nifty_candle: Optional[Candle] = None,
        india_vix: Optional[float] = None,
    ) -> IndicatorSnapshot:
        """
        Process a 5-minute candle for a stock with optional macro context.
        Strictly prevents look-ahead bias and out-of-order execution.
        """
        self._validate_candle(candle)
        symbol = candle.symbol.upper().strip()

        # Update macro indicators first if provided
        if nifty_candle is not None:
            self._validate_candle(nifty_candle)
            if nifty_candle.timestamp > candle.timestamp:
                raise LookAheadViolationError(
                    f"NIFTY candle timestamp {nifty_candle.timestamp} is in the future relative to stock candle {candle.timestamp}"
                )
            self.nifty_indicator.update_candle(nifty_candle)

        if india_vix is not None:
            if india_vix < 0:
                raise IndicatorValidationError(f"India VIX cannot be negative: {india_vix}")
            self.vix_filter.update_vix(india_vix)

        # Check for multi-session transition
        self._check_session_transition(candle.timestamp.date())

        coordinator = self._get_or_create_coordinator(symbol)

        # Look-ahead chronological check
        last_ts = self._last_completed_timestamps.get(symbol)
        if last_ts is not None and candle.timestamp < last_ts:
            raise LookAheadViolationError(
                f"Received out-of-order candle for {symbol}: timestamp {candle.timestamp} < last completed {last_ts}"
            )

        if is_forming or not candle.is_closed:
            # FORMING CANDLE: Return non-mutating preview without committing to permanent state
            snapshot = self._preview_forming_candle(symbol, candle, coordinator)
            return snapshot

        # COMPLETED CANDLE: Commit permanently to coordinator state
        if last_ts is not None and candle.timestamp == last_ts:
            raise LookAheadViolationError(
                f"Duplicate completed candle timestamp {candle.timestamp} for {symbol}"
            )

        snapshot = coordinator.process_completed_candle(
            candle=candle,
            nifty_indicator=self.nifty_indicator,
            vix_filter=self.vix_filter,
        )

        # Record state
        self._last_completed_timestamps[symbol] = candle.timestamp
        self._latest_snapshots[symbol] = snapshot
        self._latest_close_by_symbol[symbol] = candle.close

        return snapshot

    def _preview_forming_candle(
        self,
        symbol: str,
        candle: Candle,
        coordinator: StockIndicatorCoordinator,
    ) -> IndicatorSnapshot:
        """
        Compute temporary snapshot for a forming bar without mutating permanent indicator states.
        """
        preview_vwap = coordinator.vwap_calc.preview_candle(candle)
        preview_atr = coordinator.atr_calc.preview_candle(candle)
        orb_levels = coordinator.orb_calc.get_levels()
        prior_avg_vol = coordinator.volume_sma_calc.get_prior_average_volume()
        surge_ratio = coordinator.volume_sma_calc.calculate_surge_ratio(candle.volume)
        gap_info = coordinator._day_gap_info
        gap_pct = gap_info.gap_pct if gap_info else None

        return IndicatorSnapshot(
            symbol=symbol,
            timestamp=candle.timestamp,
            close=candle.close,
            vwap=preview_vwap,
            atr_14=preview_atr,
            orb_high=orb_levels.high if orb_levels else None,
            orb_low=orb_levels.low if orb_levels else None,
            orb_is_complete=orb_levels.is_complete if orb_levels else False,
            prev_avg_volume_10=prior_avg_vol,
            current_volume=candle.volume,
            volume_surge_ratio=surge_ratio,
            gap_pct=gap_pct,
            nifty_close=self.nifty_indicator.last_close,
            nifty_vwap=self.nifty_indicator.vwap,
            nifty_regime=self.nifty_indicator.regime,
            india_vix=self.vix_filter.current_vix,
            vix_is_acceptable=self.vix_filter.is_trading_allowed(),
        )

    # ==========================================================================
    # Convenience Query Methods
    # ==========================================================================

    def get_snapshot(self, symbol: str) -> Optional[IndicatorSnapshot]:
        return self._latest_snapshots.get(symbol.upper().strip())

    def get_session_vwap(self, symbol: str) -> Optional[float]:
        coord = self._coordinators.get(symbol.upper().strip())
        return coord.vwap_calc.value if coord else None

    def get_atr(self, symbol: str) -> Optional[float]:
        coord = self._coordinators.get(symbol.upper().strip())
        return coord.atr_calc.value if coord else None

    def get_orb_high(self, symbol: str) -> Optional[float]:
        coord = self._coordinators.get(symbol.upper().strip())
        return coord.orb_calc.high if coord else None

    def get_orb_low(self, symbol: str) -> Optional[float]:
        coord = self._coordinators.get(symbol.upper().strip())
        return coord.orb_calc.low if coord else None

    def get_volume_average(self, symbol: str) -> Optional[float]:
        coord = self._coordinators.get(symbol.upper().strip())
        return coord.volume_sma_calc.get_prior_average_volume() if coord else None

    def get_volume_ratio(self, symbol: str) -> Optional[float]:
        snap = self.get_snapshot(symbol)
        return snap.volume_surge_ratio if snap else None

    def get_gap_pct(self, symbol: str) -> Optional[float]:
        snap = self.get_snapshot(symbol)
        return snap.gap_pct if snap else None

    def get_nifty_vwap(self) -> Optional[float]:
        return self.nifty_indicator.vwap

    def get_nifty_regime(self) -> MarketRegime:
        return self.nifty_indicator.regime

    def get_vix_value(self) -> Optional[float]:
        return self.vix_filter.current_vix

    def is_vix_acceptable(self) -> bool:
        return self.vix_filter.is_trading_allowed()

    def reset(self) -> None:
        """Completely reset the indicator engine state."""
        self.nifty_indicator.reset()
        self.vix_filter.reset()
        self._coordinators.clear()
        self._current_session_date = None
        self._last_completed_timestamps.clear()
        self._latest_snapshots.clear()
        self._latest_close_by_symbol.clear()
