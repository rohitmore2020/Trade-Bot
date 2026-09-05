"""
India VIX Volatility Filter Indicator.

Tracks India VIX levels and determines volatility regime:
- LOW: VIX < 10.0 (compressed volatility / low breakout follow-through)
- NORMAL: 10.0 <= VIX <= 24.0 (ideal trading regime for VWAP-ORB)
- ELEVATED: 24.0 < VIX <= 28.0 (caution / reduced sizing)
- EXTREME: VIX > 28.0 (circuit breaker / trading blocked)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class VIXRegime(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    EXTREME = "EXTREME"


class IndiaVIXFilter:
    """
    Evaluates India VIX against risk and strategy parameters.
    """

    def __init__(
        self,
        min_vix: float = 10.0,
        max_vix: float = 24.0,
        extreme_vix: float = 28.0,
    ) -> None:
        self.min_vix = min_vix
        self.max_vix = max_vix
        self.extreme_vix = extreme_vix
        self._current_vix: Optional[float] = None

    @property
    def current_vix(self) -> Optional[float]:
        return self._current_vix

    @property
    def is_ready(self) -> bool:
        return self._current_vix is not None

    def update_vix(self, vix_value: float) -> VIXRegime:
        """Update current VIX value and return volatility regime."""
        self._current_vix = round(float(vix_value), 2)
        return self.get_regime()

    def get_regime(self) -> VIXRegime:
        """Get the current VIX volatility classification."""
        if self._current_vix is None:
            return VIXRegime.NORMAL

        if self._current_vix < self.min_vix:
            return VIXRegime.LOW
        elif self._current_vix <= self.max_vix:
            return VIXRegime.NORMAL
        elif self._current_vix <= self.extreme_vix:
            return VIXRegime.ELEVATED
        else:
            return VIXRegime.EXTREME

    def is_trading_allowed(self) -> bool:
        """
        Returns True if VIX is within normal or non-extreme range.
        Rejects trading if VIX is in EXTREME territory (> 28.0).
        """
        if self._current_vix is None:
            return True  # If VIX feed is unavailable, allow with default risk
        return self._current_vix <= self.extreme_vix

    def is_ideal_regime(self) -> bool:
        """Returns True if VIX is strictly in NORMAL regime."""
        return self.get_regime() == VIXRegime.NORMAL

    def reset(self) -> None:
        """Reset VIX tracking state."""
        self._current_vix = None
