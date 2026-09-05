"""
Indicator Exceptions.

Strict, fail-fast exception hierarchy for indicator calculation, validation,
and look-ahead prevention.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from trade_bot.domain.exceptions import TradingPlatformError


class IndicatorError(TradingPlatformError):
    """Base exception for all indicator computation errors."""
    pass


class IndicatorValidationError(IndicatorError):
    """Raised when incoming candle or tick data violates mathematical invariants."""
    pass


class LookAheadViolationError(IndicatorError):
    """Raised when market data is ingested out of chronological order or violates lookahead rules."""
    pass


class InsufficientDataError(IndicatorError):
    """Raised when an indicator is queried before sufficient warm-up periods are available."""
    pass


class SessionBoundaryError(IndicatorError):
    """Raised when an invalid session transition or boundary state occurs."""
    pass
