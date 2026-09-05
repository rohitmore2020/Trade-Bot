"""
Strategy Interfaces and Strategy Context.

Strictly decouples signal logic from broker/execution. Strategies operate on a read-only
`StrategyContext` and emit `Signal` objects without side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Protocol, runtime_checkable
from trade_bot.domain.models import AccountBalance, Candle, Position, Signal, Tick


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """
    Read-only view of current market state, time, active positions, and account metrics.
    Provided to strategy logic on every tick/candle event to ensure pure execution.
    """
    current_time: datetime
    positions: Dict[str, Position]
    account_balance: AccountBalance
    active_candles_1m: Dict[str, Candle]
    active_candles_5m: Dict[str, Candle]


@runtime_checkable
class IStrategy(Protocol):
    """Protocol for quantitative trading strategies."""

    @property
    def name(self) -> str:
        """Unique strategy identifier."""
        ...

    def on_start(self, symbols: List[str]) -> None:
        """Initialize indicators, subscriptions, and state at session start."""
        ...

    def on_tick(self, tick: Tick, context: StrategyContext) -> List[Signal]:
        """Process real-time tick event and emit any actionable signals."""
        ...

    def on_candle(self, candle: Candle, context: StrategyContext) -> List[Signal]:
        """Process completed candle bar and emit any actionable signals."""
        ...

    def on_stop(self) -> None:
        """Cleanup strategy state at session end."""
        ...
