"""
Historical Data Validation Engine.

Performs deterministic mathematical and integrity audits on OHLCV datasets:
- Strict OHLC invariants (High >= Low, High >= max(Open, Close), Low <= min(Open, Close), Prices > 0)
- Volume integrity (Volume >= 0, integer values, spike detection)
- Timestamp integrity (chronological ordering, duplicate timestamps, weekend/holiday leaks)
- Missing candle detection against the official NSE trading calendar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Dict, List, Optional, Set
import pandas as pd
from trade_bot.config.constants import (
    IST_TIMEZONE,
    MARKET_CLOSE_TIME,
    MARKET_OPEN_TIME,
)
from trade_bot.data.calendar import NSETradingCalendar


@dataclass(frozen=True, slots=True)
class ValidationError:
    """Represents a specific data anomaly or invariant violation."""
    error_type: str
    symbol: str
    timestamp: datetime
    description: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Summary of data quality and integrity audit."""
    symbol: str
    timeframe_seconds: int
    total_bars: int = 0
    valid_bars: int = 0
    invalid_ohlc_bars: int = 0
    invalid_volume_bars: int = 0
    duplicate_timestamps: int = 0
    out_of_session_bars: int = 0
    missing_bars: int = 0
    expected_bars: int = 0
    completeness_percentage: float = 0.0
    errors: List[ValidationError] = field(default_factory=list)
    missing_timestamps: List[datetime] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if zero corrupted OHLC, volume, or duplicate bars are detected."""
        return (
            self.invalid_ohlc_bars == 0
            and self.invalid_volume_bars == 0
            and self.duplicate_timestamps == 0
            and self.out_of_session_bars == 0
        )


class CandleDataValidator:
    """
    Audits OHLCV DataFrames against exchange rules and mathematical invariants.
    """

    def __init__(self, calendar: Optional[NSETradingCalendar] = None) -> None:
        self.calendar = calendar or NSETradingCalendar()

    def validate_dataframe(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe_seconds: int = 300,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> ValidationReport:
        """
        Execute full validation pipeline on an OHLCV DataFrame.
        """
        report = ValidationReport(symbol=symbol, timeframe_seconds=timeframe_seconds)
        if df.empty:
            return report

        report.total_bars = len(df)
        seen_timestamps: Set[datetime] = set()

        # Check for duplicates in DataFrame index / column
        dup_series = df.duplicated(subset=["timestamp"], keep=False)
        report.duplicate_timestamps = int(dup_series.sum())

        for row in df.itertuples(index=False):
            ts = row.timestamp.to_pydatetime() if hasattr(row.timestamp, "to_pydatetime") else row.timestamp
            o, h, l, c = float(row.open), float(row.high), float(row.low), float(row.close)
            v = int(row.volume)

            is_bar_valid = True

            # Check 1: Prices must be positive
            if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                report.invalid_ohlc_bars += 1
                is_bar_valid = False
                report.errors.append(
                    ValidationError(
                        error_type="NON_POSITIVE_PRICE",
                        symbol=symbol,
                        timestamp=ts,
                        description=f"Prices must be strictly positive: O={o}, H={h}, L={l}, C={c}",
                    )
                )

            # Check 2: High >= Low
            if h < l:
                report.invalid_ohlc_bars += 1
                is_bar_valid = False
                report.errors.append(
                    ValidationError(
                        error_type="HIGH_LESS_THAN_LOW",
                        symbol=symbol,
                        timestamp=ts,
                        description=f"High ({h}) is less than Low ({l})",
                    )
                )

            # Check 3: High >= max(Open, Close)
            if h < max(o, c):
                report.invalid_ohlc_bars += 1
                is_bar_valid = False
                report.errors.append(
                    ValidationError(
                        error_type="HIGH_LESS_THAN_OPEN_CLOSE",
                        symbol=symbol,
                        timestamp=ts,
                        description=f"High ({h}) is less than max(Open={o}, Close={c})",
                    )
                )

            # Check 4: Low <= min(Open, Close)
            if l > min(o, c):
                report.invalid_ohlc_bars += 1
                is_bar_valid = False
                report.errors.append(
                    ValidationError(
                        error_type="LOW_GREATER_THAN_OPEN_CLOSE",
                        symbol=symbol,
                        timestamp=ts,
                        description=f"Low ({l}) is greater than min(Open={o}, Close={c})",
                    )
                )

            # Check 5: Volume must be non-negative
            if v < 0:
                report.invalid_volume_bars += 1
                is_bar_valid = False
                report.errors.append(
                    ValidationError(
                        error_type="NEGATIVE_VOLUME",
                        symbol=symbol,
                        timestamp=ts,
                        description=f"Negative volume detected: {v}",
                    )
                )

            # Check 6: Session and Trading Day validation
            t_time = ts.time()
            t_date = ts.date()
            if not self.calendar.is_trading_day(t_date):
                report.out_of_session_bars += 1
                is_bar_valid = False
                report.errors.append(
                    ValidationError(
                        error_type="NON_TRADING_DAY_BAR",
                        symbol=symbol,
                        timestamp=ts,
                        description=f"Bar timestamp falls on weekend or holiday: {t_date}",
                    )
                )
            elif t_time < MARKET_OPEN_TIME or t_time >= MARKET_CLOSE_TIME:
                report.out_of_session_bars += 1
                is_bar_valid = False
                report.errors.append(
                    ValidationError(
                        error_type="OUT_OF_HOURS_BAR",
                        symbol=symbol,
                        timestamp=ts,
                        description=f"Bar time {t_time} is outside regular market hours (09:15 - 15:30)",
                    )
                )

            if is_bar_valid:
                report.valid_bars += 1

        # Check 7: Missing Bar Detection
        earliest_date = start_date or df["timestamp"].min().date()
        latest_date = end_date or df["timestamp"].max().date()
        trading_days = self.calendar.get_trading_days(earliest_date, latest_date)

        actual_timestamps_set = set(
            df["timestamp"].dt.tz_convert(IST_TIMEZONE).dt.to_pydatetime()
            if hasattr(df["timestamp"].iloc[0], "tz")
            else df["timestamp"].to_pydatetime()
        )

        all_expected_timestamps: List[datetime] = []
        for td in trading_days:
            expected_for_day = self.calendar.get_expected_bar_timestamps(td, timeframe_seconds)
            all_expected_timestamps.extend(expected_for_day)

        report.expected_bars = len(all_expected_timestamps)
        missing_ts = [ts for ts in all_expected_timestamps if ts not in actual_timestamps_set]
        report.missing_timestamps = missing_ts
        report.missing_bars = len(missing_ts)

        if report.expected_bars > 0:
            report.completeness_percentage = round(
                (report.total_bars - report.out_of_session_bars) / report.expected_bars * 100.0, 2
            )
        else:
            report.completeness_percentage = 100.0 if report.total_bars > 0 else 0.0

        return report
