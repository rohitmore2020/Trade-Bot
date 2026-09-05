"""
VWAP-ORB Strategy Domain and Data Models.

Provides strongly typed, deterministic data models for the VWAP-ORB strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class MarketRegime(str, Enum):
    """Benchmark market regime determined by NIFTY relative to its VWAP."""
    BULLISH = "BULLISH"  # NIFTY > VWAP -> Long only
    BEARISH = "BEARISH"  # NIFTY < VWAP -> Short only
    NEUTRAL = "NEUTRAL"  # NIFTY == VWAP -> No trades


class SignalTriggerReason(str, Enum):
    """Specific reason signal triggered or failed."""
    LONG_ENTRY = "LONG_ENTRY"
    SHORT_ENTRY = "SHORT_ENTRY"
    REGIME_MISMATCH = "REGIME_MISMATCH"
    OUTSIDE_TRADING_WINDOW = "OUTSIDE_TRADING_WINDOW"
    NO_PULLBACK = "NO_PULLBACK"
    NOT_BULLISH_CANDLE = "NOT_BULLISH_CANDLE"
    NOT_BEARISH_CANDLE = "NOT_BEARISH_CANDLE"
    VOLUME_SURGE_UNMET = "VOLUME_SURGE_UNMET"
    ORB_CONDITION_UNMET = "ORB_CONDITION_UNMET"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VwapOrbStrategyConfig(BaseModel):
    """
    Validated configuration parameters for the VWAP-ORB strategy.
    """
    # Universe Filters
    fno_only: bool = True
    min_turnover_cr: float = Field(default=100.0, ge=1.0)
    min_atr_pct: float = Field(default=1.5, ge=0.1)
    max_atr_pct: float = Field(default=6.0, ge=0.5)
    atr_universe_period: int = Field(default=20, ge=5)
    min_price: float = Field(default=200.0, ge=1.0)
    max_price: float = Field(default=5000.0, ge=10.0)
    min_premarket_volume_pct: float = Field(default=0.10, ge=0.0)
    min_gap_pct: float = Field(default=0.01, ge=0.0)

    # Operational Timings (IST)
    orb_start_time: time = Field(default=time(9, 15, 0))
    orb_end_time: time = Field(default=time(9, 30, 0))
    window_start: time = Field(default=time(9, 45, 0))
    window_end: time = Field(default=time(14, 30, 0))

    # Signal & Execution Rules
    candle_timeframe_seconds: int = Field(default=300, ge=60)  # 5 minutes
    pullback_tolerance_long: float = Field(default=1.002, ge=1.0)
    pullback_tolerance_short: float = Field(default=0.998, le=1.0)
    volume_surge_multiplier: float = Field(default=1.5, ge=1.0)
    volume_sma_period: int = Field(default=10, ge=2)
    limit_order_offset_pct: float = Field(default=0.0005, ge=0.0)

    # Risk & Exits
    atr_period: int = Field(default=14, ge=2)
    stop_loss_atr_mult: float = Field(default=1.5, ge=0.5)
    trailing_stop_atr_mult: float = Field(default=2.0, ge=0.5)
    vwap_exit_enabled: bool = True

    # Account & Portfolio Risk
    risk_per_trade_pct: float = Field(default=0.005, gt=0.0, le=0.05)  # 0.5%
    max_capital_per_trade_pct: float = Field(default=0.20, gt=0.0, le=1.0)  # 20%
    max_open_positions: int = Field(default=3, ge=1, le=10)
    max_daily_trades: int = Field(default=6, ge=1, le=50)
    max_daily_loss_pct: float = Field(default=0.02, gt=0.0, le=0.10)  # 2.0%

    @field_validator("max_atr_pct")
    @classmethod
    def validate_atr_bounds(cls, v: float, info) -> float:
        min_atr = info.data.get("min_atr_pct", 1.5)
        if v <= min_atr:
            raise ValueError(f"max_atr_pct ({v}) must be greater than min_atr_pct ({min_atr})")
        return v

    @field_validator("max_price")
    @classmethod
    def validate_price_bounds(cls, v: float, info) -> float:
        min_p = info.data.get("min_price", 200.0)
        if v <= min_p:
            raise ValueError(f"max_price ({v}) must be greater than min_price ({min_p})")
        return v


@dataclass(frozen=True, slots=True)
class UniverseCandidate:
    """Candidate stock evaluated for daily trading universe eligibility."""
    symbol: str
    price: float
    avg_daily_turnover_cr: float
    atr_20d_pct: float
    premarket_volume_pct: float
    overnight_gap_pct: float
    is_fno_eligible: bool = True

    @property
    def is_eligible(self) -> bool:
        """Evaluates whether the candidate meets all baseline criteria."""
        return (
            self.is_fno_eligible
            and (self.avg_daily_turnover_cr >= 100.0)
            and (1.5 <= self.atr_20d_pct <= 6.0)
            and (200.0 <= self.price <= 5000.0)
            and (self.premarket_volume_pct >= 0.10 or abs(self.overnight_gap_pct) >= 0.01)
        )


@dataclass(frozen=True, slots=True)
class SignalEvaluationResult:
    """Detailed deterministic outcome of signal evaluation on a bar."""
    symbol: str
    timestamp: datetime
    is_signal: bool
    trigger_reason: SignalTriggerReason
    limit_entry_price: Optional[float] = None
    initial_stop_price: Optional[float] = None
    atr_value: Optional[float] = None
    criteria_checks: Dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PositionSizingResult:
    """Outcome of risk-budgeted position sizing."""
    quantity: int
    entry_price: float
    stop_price: float
    risk_per_share: float
    total_risk_amount: float
    notional_value: float
    is_capital_capped: bool
