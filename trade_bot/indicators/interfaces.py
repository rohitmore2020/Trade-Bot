"""
Indicator Interfaces, Protocols, and Value Objects.

Ensures all mathematical and technical indicators are deterministic, pure, and state-isolated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Protocol, runtime_checkable
from trade_bot.domain.enums import MarketRegime
from trade_bot.domain.models import Candle, Tick


@runtime_checkable
class IIndicator(Protocol):
    """Protocol for streaming technical and mathematical indicators."""

    @property
    def is_ready(self) -> bool:
        """Returns True if sufficient data points have been received."""
        ...

    def update_tick(self, tick: Tick) -> Any:
        """Update indicator state using a tick."""
        ...

    def update_candle(self, candle: Candle) -> Any:
        """Update indicator state using a completed or forming candle."""
        ...

    def reset(self) -> None:
        """Reset indicator state (e.g., at daily session start)."""
        ...


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    """
    Immutable snapshot of all indicator values for an instrument at candle t.
    Guarantees no look-ahead bias: only values derived from candles <= t are present.
    """
    symbol: str
    timestamp: datetime
    close: float
    vwap: Optional[float]
    atr_14: Optional[float]
    orb_high: Optional[float]
    orb_low: Optional[float]
    orb_is_complete: bool
    prev_avg_volume_10: Optional[float]
    current_volume: int
    volume_surge_ratio: Optional[float]
    gap_pct: Optional[float]
    nifty_close: Optional[float] = None
    nifty_vwap: Optional[float] = None
    nifty_regime: Optional[MarketRegime] = None
    india_vix: Optional[float] = None
    vix_is_acceptable: bool = True
