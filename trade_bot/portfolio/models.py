"""
Pure Domain Models for Portfolio & Trading-State Management.

Defines:
- Fill (confirmed execution slice from broker/exchange)
- CompletedTrade (closed round-trip trade with full audit)
- PnLBreakdown (gross, net, transaction costs, slippage, realized, unrealized)
- TradingSession (intraday trading session lifecycle)
- DailyRiskState (intraday risk constraint tracking)
- PortfolioSnapshot (immutable state snapshot of portfolio)

Zero infrastructure dependencies; pure business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Optional

from trade_bot.domain.enums import OrderSide, TradingSessionStatus
from trade_bot.domain.models import Position, utc_now


@dataclass(frozen=True, slots=True)
class Fill:
    """
    Confirmed execution fill event from the exchange.
    Derived from real execution rather than unconfirmed intent.
    """
    fill_id: str
    order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    timestamp: datetime
    expected_price: Optional[float] = None
    brokerage: float = 0.0
    stt_and_taxes: float = 0.0
    slippage: float = 0.0
    exchange: str = "NSE"


@dataclass(frozen=True, slots=True)
class CompletedTrade:
    """
    Completed round-trip position or closed position slice.
    """
    trade_id: str
    symbol: str
    side: OrderSide  # Entry side (BUY for Long, SELL for Short)
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    gross_pnl: float
    transaction_costs: float
    slippage: float
    net_pnl: float
    exit_reason: Optional[str] = None
    market_regime: Optional[str] = None


@dataclass(frozen=True, slots=True)
class PnLBreakdown:
    """
    Comprehensive separation of P&L components.
    """
    gross_realized: float = 0.0
    net_realized: float = 0.0
    unrealized: float = 0.0
    total_transaction_costs: float = 0.0
    total_slippage: float = 0.0
    total_net_pnl: float = 0.0


@dataclass
class TradingSession:
    """
    Intraday trading session lifecycle tracker.
    """
    session_id: str
    trading_date: date
    status: TradingSessionStatus = TradingSessionStatus.OPEN
    start_time: datetime = field(default_factory=utc_now)
    end_time: Optional[datetime] = None
    is_active: bool = True

    def close(self, timestamp: Optional[datetime] = None) -> None:
        self.status = TradingSessionStatus.CLOSED
        self.end_time = timestamp or utc_now()
        self.is_active = False


@dataclass
class DailyRiskState:
    """
    Tracks session risk constraints dynamically.
    """
    daily_loss_limit: float
    current_daily_loss: float = 0.0
    max_daily_loss_breached: bool = False
    max_trades_limit: int = 6
    trades_executed_today: int = 0
    max_positions_limit: int = 3
    current_open_positions: int = 0
    max_sector_exposure_pct: float = 0.40
    current_sector_exposures: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """
    Immutable point-in-time snapshot of complete portfolio state.
    """
    timestamp: datetime
    session_id: str
    initial_capital: float
    available_cash: float
    used_margin: float
    total_equity: float
    pnl: PnLBreakdown
    total_exposure: float
    open_positions_count: int
    open_positions: Dict[str, Position]
    daily_trade_count: int
    daily_order_count: int
