"""
Backtesting Interfaces and Protocols.

Defines protocols for simulation clocks, historical data feeds,
execution simulators, and backtest runners.
Zero broker or external network dependencies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Protocol, Tuple, runtime_checkable

from trade_bot.domain.enums import OrderSide, OrderStatus
from trade_bot.domain.models import Candle, Order, OrderRequest
from trade_bot.portfolio.models import Fill


@runtime_checkable
class ISimulationClock(Protocol):
    """Protocol for advancing and querying simulation time."""

    @property
    def current_time(self) -> datetime:
        """Current simulation timestamp."""
        ...

    def advance_to(self, timestamp: datetime) -> None:
        """Advance the simulation time strictly forward."""
        ...

    def is_trading_day(self, dt: Optional[datetime] = None) -> bool:
        """Check if date is a valid trading session."""
        ...

    def is_orb_period(self, dt: Optional[datetime] = None) -> bool:
        """Check if time is within the opening range period (09:15 - 09:30 IST)."""
        ...

    def is_trading_window(self, dt: Optional[datetime] = None) -> bool:
        """Check if time is within active strategy signal window (09:45 - 14:30 IST)."""
        ...

    def is_forced_exit_time(self, dt: Optional[datetime] = None) -> bool:
        """Check if mandatory exit time (14:30:00 IST) has arrived."""
        ...


@runtime_checkable
class IHistoricalDataFeed(Protocol):
    """Protocol for streaming historical market bars in strict chronological order."""

    def load(self) -> None:
        """Load and index historical candle datasets."""
        ...

    def stream_bars(self) -> Iterator[Tuple[datetime, Dict[str, Candle]]]:
        """
        Yields (timestamp, {symbol: candle}) for each bar interval in ascending order.
        Strictly prevents look-ahead bias: only candles up to the current bar are yielded.
        """
        ...

    def get_symbols(self) -> List[str]:
        """Return unique symbols available in this feed."""
        ...


@runtime_checkable
class IExecutionSimulator(Protocol):
    """Protocol for simulating realistic execution of orders."""

    def submit_limit_order(
        self,
        order_request: OrderRequest,
        timeout_bars: int = 1,
    ) -> Order:
        """Stage a pending limit order with an expiration timeout."""
        ...

    def set_stop_loss(
        self,
        symbol: str,
        side: OrderSide,
        stop_price: float,
        quantity: int,
        client_order_id: str,
    ) -> None:
        """Register or update an active stop-loss order (SL-M)."""
        ...

    def update_stop_loss(self, symbol: str, new_stop: float) -> None:
        """Ratchets an active trailing stop loss."""
        ...

    def execute_market_exit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        current_price: float,
        timestamp: datetime,
        reason: str,
    ) -> Fill:
        """Executes an immediate market order with modeled slippage."""
        ...

    def process_bar(
        self,
        candle: Candle,
    ) -> List[Fill]:
        """
        Evaluates pending limit orders, active stop losses, and order timeouts
        against the bar's price action (Open, High, Low, Close).
        Returns any generated execution Fills.
        """
        ...

    def cancel_all_pending(self, reason: str) -> List[Order]:
        """Cancels all currently pending entry/limit orders."""
        ...


@runtime_checkable
class IBacktestRunner(Protocol):
    """Protocol for orchestrating full event-driven backtest runs."""

    def run(self) -> Any:
        """Execute backtest and return structured BacktestResult."""
        ...
