"""
Backtesting Domain Models and Configuration.

Provides strongly typed configuration, metrics, and result containers.
Zero external infrastructure dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import Order
from trade_bot.portfolio.models import CompletedTrade


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Configuration parameters for deterministic backtest execution."""
    initial_capital: float = 100_000.0
    symbols: List[str] = field(default_factory=lambda: ["RELIANCE", "TCS", "INFY"])
    nifty_symbol: str = "^NSEI"
    vix_symbol: Optional[str] = "^INDIAVIX"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    slippage_per_share: float = 0.05  # 1 tick = 0.05 INR
    slippage_pct: float = 0.0  # Optional percentage slippage (e.g. 0.0002 for 2 bps)
    limit_timeout_bars: int = 1  # 1 candle (5m) timeout for unfilled limit orders
    max_open_positions: int = 3
    max_daily_trades: int = 6
    max_daily_loss_pct: float = 0.02
    risk_per_trade_pct: float = 0.005
    max_capital_per_trade_pct: float = 0.20
    candle_timeframe_seconds: int = 300  # 5 minutes
    currency: str = "INR"
    sector_map: Dict[str, str] = field(default_factory=dict)


@dataclass
class PendingLimitOrder:
    """Tracks active limit orders awaiting price touch or expiration."""
    order: Order
    placed_at: datetime
    bars_active: int = 0
    timeout_bars: int = 1


@dataclass
class ActiveStopLoss:
    """Tracks active stop loss (SL-M) attached to an open position."""
    symbol: str
    side: OrderSide  # Exit side (SELL for Long, BUY for Short)
    stop_price: float
    quantity: int
    parent_order_id: str
    last_updated: datetime


@dataclass(frozen=True, slots=True)
class DailyPnLSummary:
    """Daily summary record of backtest trading activity."""
    trading_date: date
    trades_count: int
    winning_trades: int
    losing_trades: int
    gross_pnl: float
    transaction_costs: float
    slippage: float
    net_pnl: float
    starting_equity: float
    ending_equity: float
    return_pct: float
    max_exposure: float


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    """Comprehensive performance and risk analytics output."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    break_even_trades: int
    gross_pnl: float
    transaction_costs: float
    slippage: float
    net_pnl: float
    profit_factor: float
    expectancy: float
    win_rate: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    average_r: float
    maximum_losing_streak: int
    maximum_winning_streak: int
    peak_exposure: float
    average_exposure: float
    turnover: float


@dataclass
class BacktestResult:
    """Complete structured backtest outcome."""
    config: BacktestConfig
    metrics: BacktestMetrics
    daily_pnl: List[DailyPnLSummary]
    completed_trades: List[CompletedTrade]
    equity_curve: List[Tuple[datetime, float]]
    orders: List[Order]
    execution_start_time: Optional[datetime] = None
    execution_end_time: Optional[datetime] = None
    aggregate_cost_report: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result summary to clean serializable dictionary."""
        d: Dict[str, Any] = {
            "metrics": {
                "total_trades": self.metrics.total_trades,
                "winning_trades": self.metrics.winning_trades,
                "losing_trades": self.metrics.losing_trades,
                "break_even_trades": self.metrics.break_even_trades,
                "win_rate": round(self.metrics.win_rate, 4),
                "gross_pnl": round(self.metrics.gross_pnl, 2),
                "transaction_costs": round(self.metrics.transaction_costs, 2),
                "slippage": round(self.metrics.slippage, 2),
                "net_pnl": round(self.metrics.net_pnl, 2),
                "profit_factor": round(self.metrics.profit_factor, 4),
                "expectancy": round(self.metrics.expectancy, 2),
                "max_drawdown": round(self.metrics.max_drawdown, 2),
                "max_drawdown_pct": round(self.metrics.max_drawdown_pct, 4),
                "sharpe_ratio": round(self.metrics.sharpe_ratio, 4),
                "average_r": round(self.metrics.average_r, 4),
                "maximum_losing_streak": self.metrics.maximum_losing_streak,
                "peak_exposure": round(self.metrics.peak_exposure, 2),
                "turnover": round(self.metrics.turnover, 2),
            },
            "daily_summaries": [
                {
                    "date": d.trading_date.isoformat(),
                    "trades": d.trades_count,
                    "net_pnl": round(d.net_pnl, 2),
                    "ending_equity": round(d.ending_equity, 2),
                    "return_pct": round(d.return_pct, 4),
                }
                for d in self.daily_pnl
            ],
            "total_completed_trades": len(self.completed_trades),
        }
        if self.aggregate_cost_report is not None:
            if hasattr(self.aggregate_cost_report, "to_dict"):
                d["cost_report"] = self.aggregate_cost_report.to_dict()
            else:
                d["cost_report"] = self.aggregate_cost_report
        return d
