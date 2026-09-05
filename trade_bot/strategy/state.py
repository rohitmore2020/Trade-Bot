"""
Strategy State Machine and Lifecycle Modeling.

Explicitly models strategy state:
- Active trade tracking
- Previous signal tracking
- Re-entry limits
- Position status (FLAT, PENDING_ENTRY, OPEN, CLOSED)
- Trailing stop state ratcheting with adverse movement prevention

Zero external infrastructure dependencies; pure domain logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from trade_bot.domain.enums import OrderSide, SignalDirection
from trade_bot.domain.exceptions import DuplicateSignalError, InvalidStrategyStateTransitionError

if TYPE_CHECKING:
    from trade_bot.strategy.models import TradeIntent


class PositionStatus(str, Enum):
    """Lifecycle states of a strategy position."""
    FLAT = "FLAT"
    PENDING_ENTRY = "PENDING_ENTRY"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExitReason(str, Enum):
    """Categorized exit reason."""
    INITIAL_STOP = "INITIAL_STOP"
    TRAILING_STOP = "TRAILING_STOP"
    VWAP_FAILURE = "VWAP_FAILURE"
    TIME_EXIT = "TIME_EXIT"


@dataclass
class ActiveTradeState:
    """
    Tracks state of an active trade within the strategy for trailing stops and exits.
    """
    symbol: str
    side: OrderSide
    entry_timestamp: datetime
    entry_price: float
    initial_stop: float
    current_stop: float
    highest_price: float
    lowest_price: float
    status: PositionStatus = PositionStatus.OPEN
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None

    @property
    def direction(self) -> SignalDirection:
        """Alias for backward compatibility with SignalDirection."""
        return SignalDirection.LONG if self.side == OrderSide.BUY else SignalDirection.SHORT


@dataclass
class StrategyTradeState:
    """
    Deterministic state container for an instrument's strategy lifecycle.
    Prevents duplicate signals, guards re-entry limits, and prevents adverse stop moves.
    """
    symbol: str
    position_status: PositionStatus = PositionStatus.FLAT
    active_trade: Optional[ActiveTradeState] = None
    previous_signal: Optional[TradeIntent] = None
    trade_count: int = 0
    max_trades_per_session: int = 2
    last_exit_timestamp: Optional[datetime] = None
    last_exit_reason: Optional[str] = None

    def can_enter(self) -> tuple[bool, Optional[str]]:
        """
        Evaluates whether a new trade can be initiated.
        """
        if self.position_status != PositionStatus.FLAT:
            return False, f"Position status is {self.position_status.value}, cannot open new trade"
        if self.trade_count >= self.max_trades_per_session:
            return False, f"Max trades per session reached ({self.trade_count}/{self.max_trades_per_session})"
        return True, None

    def is_duplicate_signal(self, signal: TradeIntent) -> bool:
        """
        Checks if the candidate signal duplicates the immediate previous signal on timestamp and side.
        """
        if self.previous_signal is None:
            return False
        return (
            self.previous_signal.timestamp == signal.timestamp
            and self.previous_signal.side == signal.side
        )

    def record_signal(self, signal: TradeIntent) -> None:
        """
        Records a signal. Rejects duplicate signals with DuplicateSignalError.
        """
        if self.is_duplicate_signal(signal):
            raise DuplicateSignalError(
                f"Duplicate signal detected for {self.symbol} at {signal.timestamp} with side {signal.side.value}"
            )
        self.previous_signal = signal
        if signal.intent_type == "ENTRY" and self.position_status == PositionStatus.FLAT:
            self.position_status = PositionStatus.PENDING_ENTRY

    def open_trade(
        self,
        timestamp: datetime,
        entry_price: float,
        initial_stop: float,
        side: OrderSide,
    ) -> ActiveTradeState:
        """
        Transitions state to OPEN and initiates active trade tracking.
        Guards against invalid state transitions.
        """
        if self.position_status == PositionStatus.OPEN:
            raise InvalidStrategyStateTransitionError(
                f"Cannot open trade for {self.symbol}: already in OPEN status"
            )
        if self.position_status == PositionStatus.CLOSED:
            raise InvalidStrategyStateTransitionError(
                f"Cannot open trade directly from CLOSED state for {self.symbol}"
            )
        if self.trade_count >= self.max_trades_per_session:
            raise InvalidStrategyStateTransitionError(
                f"Cannot open trade: max session trades exceeded ({self.trade_count} >= {self.max_trades_per_session})"
            )

        trade = ActiveTradeState(
            symbol=self.symbol,
            side=side,
            entry_timestamp=timestamp,
            entry_price=entry_price,
            initial_stop=initial_stop,
            current_stop=initial_stop,
            highest_price=entry_price,
            lowest_price=entry_price,
            status=PositionStatus.OPEN,
        )
        self.active_trade = trade
        self.position_status = PositionStatus.OPEN
        self.trade_count += 1
        return trade

    def update_watermark(self, high: float, low: float) -> None:
        """
        Updates peak and trough watermarks for active trade.
        """
        if self.position_status != PositionStatus.OPEN or self.active_trade is None:
            raise InvalidStrategyStateTransitionError(
                f"Cannot update watermark for {self.symbol}: position is not OPEN"
            )
        self.active_trade.highest_price = max(self.active_trade.highest_price, high)
        self.active_trade.lowest_price = min(self.active_trade.lowest_price, low)

    def update_trailing_stop(self, new_stop: float) -> float:
        """
        Ratchets the trailing stop price.
        Enforces invariant: Trailing stop must NEVER move in the unfavorable direction.
        """
        if self.position_status != PositionStatus.OPEN or self.active_trade is None:
            raise InvalidStrategyStateTransitionError(
                f"Cannot update trailing stop for {self.symbol}: position is not OPEN"
            )

        trade = self.active_trade
        if trade.side == OrderSide.BUY:
            if new_stop < trade.current_stop:
                raise InvalidStrategyStateTransitionError(
                    f"Adverse trailing stop movement disallowed for LONG: {new_stop} < {trade.current_stop}"
                )
            trade.current_stop = max(trade.current_stop, new_stop)
        elif trade.side == OrderSide.SELL:
            if new_stop > trade.current_stop:
                raise InvalidStrategyStateTransitionError(
                    f"Adverse trailing stop movement disallowed for SHORT: {new_stop} > {trade.current_stop}"
                )
            trade.current_stop = min(trade.current_stop, new_stop)

        return trade.current_stop

    def close_trade(
        self,
        timestamp: datetime,
        exit_price: float,
        reason: ExitReason | str,
    ) -> ActiveTradeState:
        """
        Closes active trade and transitions position status back to FLAT.
        """
        if self.position_status != PositionStatus.OPEN or self.active_trade is None:
            raise InvalidStrategyStateTransitionError(
                f"Cannot close trade for {self.symbol}: position status is {self.position_status.value}"
            )

        trade = self.active_trade
        trade.status = PositionStatus.CLOSED
        trade.exit_timestamp = timestamp
        trade.exit_price = exit_price
        trade.exit_reason = str(reason.value if isinstance(reason, ExitReason) else reason)

        self.last_exit_timestamp = timestamp
        self.last_exit_reason = trade.exit_reason
        self.active_trade = None
        self.position_status = PositionStatus.FLAT

        return trade

    def reset_session(self) -> None:
        """Resets daily session tracking."""
        self.position_status = PositionStatus.FLAT
        self.active_trade = None
        self.previous_signal = None
        self.trade_count = 0
        self.last_exit_timestamp = None
        self.last_exit_reason = None
