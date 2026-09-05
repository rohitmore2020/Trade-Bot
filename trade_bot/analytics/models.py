"""
Data Models for Performance Analytics and Multi-Dimensional Reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class ReturnMetrics:
    """Return and volatility statistics."""
    total_return_pct: float
    cagr_pct: float
    daily_volatility_pct: float
    annualized_volatility_pct: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "total_return_pct": self.total_return_pct,
            "cagr_pct": self.cagr_pct,
            "daily_volatility_pct": self.daily_volatility_pct,
            "annualized_volatility_pct": self.annualized_volatility_pct,
        }


@dataclass(frozen=True, slots=True)
class PnLMetrics:
    """Profit and Loss metrics."""
    gross_pnl: float
    net_pnl: float
    profit_factor: float
    expectancy: float
    win_rate: float
    avg_winner: float
    avg_loser: float
    payoff_ratio: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "profit_factor": self.profit_factor,
            "expectancy": self.expectancy,
            "win_rate": self.win_rate,
            "avg_winner": self.avg_winner,
            "avg_loser": self.avg_loser,
            "payoff_ratio": self.payoff_ratio,
        }


@dataclass(frozen=True, slots=True)
class DrawdownMetrics:
    """Drawdown statistics."""
    max_drawdown_amount: float
    max_drawdown_pct: float
    avg_drawdown_pct: float
    max_drawdown_duration_days: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_drawdown_amount": self.max_drawdown_amount,
            "max_drawdown_pct": self.max_drawdown_pct,
            "avg_drawdown_pct": self.avg_drawdown_pct,
            "max_drawdown_duration_days": self.max_drawdown_duration_days,
        }


@dataclass(frozen=True, slots=True)
class TradeStatsMetrics:
    """Trade distribution and duration metrics."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    break_even_trades: int
    max_consecutive_wins: int
    max_consecutive_losses: int
    avg_holding_duration_mins: float
    average_r: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "break_even_trades": self.break_even_trades,
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            "avg_holding_duration_mins": self.avg_holding_duration_mins,
            "average_r": self.average_r,
        }


@dataclass(frozen=True, slots=True)
class RiskMetrics:
    """Risk-adjusted return metrics."""
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
        }


@dataclass(frozen=True, slots=True)
class ExecutionMetrics:
    """Turnover, costs, and slippage metrics."""
    turnover: float
    transaction_costs: float
    slippage: float
    slippage_bps: float
    costs_as_pct_of_turnover: float
    costs_as_pct_of_gross_pnl: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "turnover": self.turnover,
            "transaction_costs": self.transaction_costs,
            "slippage": self.slippage,
            "slippage_bps": self.slippage_bps,
            "costs_as_pct_of_turnover": self.costs_as_pct_of_turnover,
            "costs_as_pct_of_gross_pnl": self.costs_as_pct_of_gross_pnl,
        }


@dataclass(frozen=True, slots=True)
class GroupBreakdown:
    """Performance breakdown for an individual category (stock, day, regime, etc.)."""
    category: str
    group_key: str
    trades_count: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_pnl: float
    transaction_costs: float
    slippage: float
    net_pnl: float
    profit_factor: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "group_key": self.group_key,
            "trades_count": self.trades_count,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "gross_pnl": self.gross_pnl,
            "transaction_costs": self.transaction_costs,
            "slippage": self.slippage,
            "net_pnl": self.net_pnl,
            "profit_factor": self.profit_factor,
        }


@dataclass(frozen=True, slots=True)
class ComprehensiveReport:
    """Master performance report containing all metrics and attribution breakdowns."""
    initial_capital: float
    final_equity: float
    returns: ReturnMetrics
    pnl: PnLMetrics
    drawdown: DrawdownMetrics
    trade_stats: TradeStatsMetrics
    risk_adjusted: RiskMetrics
    execution: ExecutionMetrics
    by_stock: List[GroupBreakdown] = field(default_factory=list)
    by_day: List[GroupBreakdown] = field(default_factory=list)
    by_month: List[GroupBreakdown] = field(default_factory=list)
    by_regime: List[GroupBreakdown] = field(default_factory=list)
    by_direction: List[GroupBreakdown] = field(default_factory=list)
    by_entry_time: List[GroupBreakdown] = field(default_factory=list)
    by_exit_reason: List[GroupBreakdown] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": {
                "initial_capital": self.initial_capital,
                "final_equity": self.final_equity,
                "total_return_pct": self.returns.total_return_pct,
                "cagr_pct": self.returns.cagr_pct,
                "gross_pnl": self.pnl.gross_pnl,
                "net_pnl": self.pnl.net_pnl,
                "win_rate": self.pnl.win_rate,
                "profit_factor": self.pnl.profit_factor,
                "expectancy": self.pnl.expectancy,
                "max_drawdown_amount": self.drawdown.max_drawdown_amount,
                "max_drawdown_pct": self.drawdown.max_drawdown_pct,
                "sharpe_ratio": self.risk_adjusted.sharpe_ratio,
                "sortino_ratio": self.risk_adjusted.sortino_ratio,
                "calmar_ratio": self.risk_adjusted.calmar_ratio,
                "total_trades": self.trade_stats.total_trades,
                "turnover": self.execution.turnover,
                "transaction_costs": self.execution.transaction_costs,
                "slippage": self.execution.slippage,
            },
            "returns": self.returns.to_dict(),
            "pnl": self.pnl.to_dict(),
            "drawdown": self.drawdown.to_dict(),
            "trade_stats": self.trade_stats.to_dict(),
            "risk_adjusted": self.risk_adjusted.to_dict(),
            "execution": self.execution.to_dict(),
            "breakdowns": {
                "by_stock": [b.to_dict() for b in self.by_stock],
                "by_day": [b.to_dict() for b in self.by_day],
                "by_month": [b.to_dict() for b in self.by_month],
                "by_regime": [b.to_dict() for b in self.by_regime],
                "by_direction": [b.to_dict() for b in self.by_direction],
                "by_entry_time": [b.to_dict() for b in self.by_entry_time],
                "by_exit_reason": [b.to_dict() for b in self.by_exit_reason],
            },
        }
