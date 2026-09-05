"""
Indicator Interfaces and Protocols.

Ensures all mathematical and technical indicators are deterministic, pure, and state-isolated.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
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
