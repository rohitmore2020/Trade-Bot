"""
Core Domain Models for Trade-Bot.

Strictly typed, deterministic data models and value objects representing financial entities.
Designed for high auditability, zero side-effects, and complete domain isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)

from trade_bot.domain.enums import (
    InstrumentType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    ProductType,
    RiskCheckResultStatus,
    SignalDirection,
    TimeInForce,
)
from trade_bot.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class Instrument:
    """Represents a tradable financial asset on an exchange."""
    symbol: str
    exchange: str = "NSE"
    segment: str = "EQ"
    instrument_type: InstrumentType = InstrumentType.EQUITY
    lot_size: int = 1
    tick_size: float = 0.05
    trading_symbol: Optional[str] = None
    isin: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise DomainValidationError("Instrument symbol cannot be empty")
        if self.lot_size <= 0:
            raise DomainValidationError(f"Lot size must be positive, got {self.lot_size}")
        if self.tick_size <= 0:
            raise DomainValidationError(f"Tick size must be positive, got {self.tick_size}")


@dataclass(frozen=True, slots=True)
class Tick:
    """Atomic market data event representing a trade or quote snapshot."""
    symbol: str
    timestamp: datetime
    last_price: float
    volume: int
    total_volume: int = 0
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    close_price: Optional[float] = None
    buy_quantity: int = 0
    sell_quantity: int = 0
    exchange: str = "NSE"

    def __post_init__(self) -> None:
        if self.last_price <= 0:
            raise DomainValidationError(f"Tick last_price must be positive, got {self.last_price}")
        if self.volume < 0:
            raise DomainValidationError(f"Tick volume cannot be negative, got {self.volume}")


@dataclass(frozen=True, slots=True)
class Candle:
    """Aggregated OHLCV bar for a given timeframe."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    timeframe_seconds: int = 60
    is_closed: bool = True

    def __post_init__(self) -> None:
        if self.open <= 0 or self.high <= 0 or self.low <= 0 or self.close <= 0:
            raise DomainValidationError(f"OHLC prices must be strictly positive: {self}")
        if self.high < self.low:
            raise DomainValidationError(f"High ({self.high}) cannot be less than Low ({self.low})")
        if self.high < max(self.open, self.close):
            raise DomainValidationError(f"High ({self.high}) is lower than Open/Close ({self.open}, {self.close})")
        if self.low > min(self.open, self.close):
            raise DomainValidationError(f"Low ({self.low}) is higher than Open/Close ({self.open}, {self.close})")
        if self.volume < 0:
            raise DomainValidationError(f"Volume cannot be negative: {self.volume}")

    @property
    def range(self) -> float:
        return round(self.high - self.low, 4)

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass(frozen=True, slots=True)
class Signal:
    """Strategy output recommending an order action."""
    signal_id: str
    symbol: str
    timestamp: datetime
    direction: SignalDirection
    strategy_name: str
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    suggested_quantity: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entry_price <= 0:
            raise DomainValidationError(f"Signal entry_price must be positive, got {self.entry_price}")
        if self.stop_loss is not None and self.stop_loss <= 0:
            raise DomainValidationError(f"Signal stop_loss must be positive, got {self.stop_loss}")


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """Intent to place an order, emitted after signal processing and risk approval."""
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    product_type: ProductType = ProductType.MIS
    time_in_force: TimeInForce = TimeInForce.DAY
    strategy_name: str = "DEFAULT"
    signal_id: Optional[str] = None
    tag: Optional[str] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.client_order_id:
            raise DomainValidationError("client_order_id cannot be empty")
        if self.quantity <= 0:
            raise DomainValidationError(f"Order quantity must be positive, got {self.quantity}")
        if self.order_type in (OrderType.LIMIT, OrderType.SL_LIMIT) and (self.price is None or self.price <= 0):
            raise DomainValidationError(f"Price must be positive for {self.order_type}")
        if self.order_type in (OrderType.SL_MARKET, OrderType.SL_LIMIT) and (
            self.trigger_price is None or self.trigger_price <= 0
        ):
            raise DomainValidationError(f"Trigger price must be positive for {self.order_type}")


@dataclass(frozen=True, slots=True)
class OrderModification:
    """Intent to modify an existing open order."""
    order_id: str
    client_order_id: str
    quantity: Optional[int] = None
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    order_type: Optional[OrderType] = None


@dataclass(frozen=True, slots=True)
class Trade:
    """Execution fill confirmation for an order."""
    trade_id: str
    order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    timestamp: datetime
    exchange: str = "NSE"
    brokerage: float = 0.0
    stt_and_taxes: float = 0.0

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise DomainValidationError(f"Trade quantity must be positive, got {self.quantity}")
        if self.price <= 0:
            raise DomainValidationError(f"Trade price must be positive, got {self.price}")


@dataclass(slots=True)
class Order:
    """Mutable domain entity tracking complete order lifecycle."""
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    product_type: ProductType = ProductType.MIS
    time_in_force: TimeInForce = TimeInForce.DAY
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    broker_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: int = 0
    average_fill_price: float = 0.0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    strategy_name: str = "DEFAULT"
    signal_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    fills: List[Trade] = field(default_factory=list)

    @property
    def remaining_quantity(self) -> int:
        return max(0, self.quantity - self.filled_quantity)

    @property
    def is_active(self) -> bool:
        return self.status in (
            OrderStatus.CREATED,
            OrderStatus.PENDING_SUBMIT,
            OrderStatus.SUBMITTED,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIALLY_FILLED,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )


@dataclass(slots=True)
class Position:
    """Tracks position state, average cost, and P&L for a symbol."""
    symbol: str
    product_type: ProductType = ProductType.MIS
    quantity: int = 0
    average_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    last_price: float = 0.0
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def side(self) -> PositionSide:
        if self.quantity > 0:
            return PositionSide.LONG
        elif self.quantity < 0:
            return PositionSide.SHORT
        return PositionSide.FLAT

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0

    @property
    def market_value(self) -> float:
        return abs(self.quantity) * self.last_price

    @property
    def total_pnl(self) -> float:
        return round(self.realized_pnl + self.unrealized_pnl, 2)

    def update_market_price(self, current_price: float) -> None:
        """Update unrealized P&L given the latest market price."""
        if current_price <= 0:
            return
        self.last_price = current_price
        if self.is_flat:
            self.unrealized_pnl = 0.0
        elif self.quantity > 0:
            self.unrealized_pnl = round((current_price - self.average_price) * self.quantity, 2)
        else:
            self.unrealized_pnl = round((self.average_price - current_price) * abs(self.quantity), 2)
        self.updated_at = utc_now()


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Current capital and margin statistics."""
    initial_capital: float
    available_cash: float
    used_margin: float
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    currency: str = "INR"
    timestamp: datetime = field(default_factory=utc_now)

    @property
    def total_equity(self) -> float:
        return round(self.available_cash + self.used_margin + self.total_unrealized_pnl, 2)


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Evaluation result from pre-trade risk management."""
    status: RiskCheckResultStatus
    reason: str
    rule_name: str
    order_request: Optional[OrderRequest] = None
    modified_quantity: Optional[int] = None

    @property
    def is_approved(self) -> bool:
        return self.status == RiskCheckResultStatus.APPROVED
