"""
Domain models and typed data containers for the Dynamic Stock Scanner.

Strictly typed, immutable value objects ensuring complete auditability and determinism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from trade_bot.domain.enums import MarketRegime


@dataclass(frozen=True, slots=True)
class StockMetricsInput:
    """
    Market metrics for a candidate stock on a given scan date.
    Supplied to the scanner pipeline for filtering and ranking.
    """
    symbol: str
    instrument_id: str
    price: float
    avg_daily_turnover_cr: float
    avg_daily_volume: float
    atr_20d: float
    atr_20d_pct: float
    prev_day_close: float
    day_open: float
    overnight_gap_pct: float
    premarket_volume: int
    premarket_volume_pct: float
    is_fno_constituent: bool = True
    is_active: bool = True
    historical_bars_count: int = 30  # Days of trading history available


@dataclass(frozen=True, slots=True)
class MarketContextInput:
    """
    Macro market state on the scan date (NIFTY benchmark and India VIX).
    """
    nifty_price: float
    nifty_vwap: float
    nifty_regime: MarketRegime
    india_vix: float
    vix_is_acceptable: bool = True


@dataclass(frozen=True, slots=True)
class FilterResult:
    """
    Outcome of an individual filter evaluation on a single stock candidate.
    """
    passed: bool
    filter_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class ScannedCandidate:
    """
    Strongly typed candidate stock emitted by CandidateScanner.
    Contains all metrics required for downstream strategy execution.
    """
    symbol: str
    instrument_id: str
    price: float
    avg_daily_turnover_cr: float
    avg_daily_volume: float
    atr_pct: float
    gap_pct: float
    premarket_volume: int
    premarket_volume_pct: float
    is_eligible: bool
    status_reason: str
    rank: Optional[int]
    scan_timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
