"""
Performance Reporter and Export Engine.

Orchestrates all analytics calculators and produces:
- Comprehensive structured PerformanceReport domain object
- JSON machine-readable output
- CSV machine-readable tables
- Clean Markdown / ASCII human-readable performance summary
"""

from __future__ import annotations

import csv
from datetime import date, datetime
import io
import json
from typing import Any, Dict, List, Optional, Tuple

from trade_bot.analytics.breakdowns import BreakdownEngine
from trade_bot.analytics.drawdown import DrawdownCalculator
from trade_bot.analytics.execution_stats import ExecutionStatsCalculator
from trade_bot.analytics.models import ComprehensiveReport, GroupBreakdown
from trade_bot.analytics.pnl import PnLAnalyticsCalculator
from trade_bot.analytics.returns import ReturnsCalculator
from trade_bot.analytics.risk_metrics import RiskMetricsCalculator
from trade_bot.analytics.trade_stats import TradeStatsCalculator
from trade_bot.portfolio.models import CompletedTrade


class PerformanceReporter:
    """
    Central analytics orchestrator generating complete audit-grade performance reports.
    """

    @classmethod
    def generate_report(
        cls,
        initial_capital: float,
        final_equity: float,
        completed_trades: List[CompletedTrade],
        equity_curve: Optional[List[Tuple[datetime, float]]] = None,
        daily_snapshots: Optional[List[Tuple[date, float]]] = None,
        total_turnover: float = 0.0,
        total_slippage: float = 0.0,
        total_costs: float = 0.0,
        calendar_days: Optional[int] = None,
    ) -> ComprehensiveReport:
        """
        Orchestrates all calculators across trades and equity series.
        Preserves the complete result set without cherry-picking.
        """
        returns = ReturnsCalculator.calculate(
            initial_capital=initial_capital,
            final_equity=final_equity,
            daily_snapshots=daily_snapshots,
            calendar_days=calendar_days,
        )

        pnl = PnLAnalyticsCalculator.calculate(completed_trades=completed_trades)

        drawdown = DrawdownCalculator.calculate(
            equity_curve=equity_curve or [],
            initial_capital=initial_capital,
        )

        trade_stats = TradeStatsCalculator.calculate(completed_trades=completed_trades)

        risk_adj = RiskMetricsCalculator.calculate(
            daily_snapshots=daily_snapshots or [],
            cagr_pct=returns.cagr_pct,
            max_drawdown_pct=drawdown.max_drawdown_pct,
        )

        execution = ExecutionStatsCalculator.calculate(
            completed_trades=completed_trades,
            total_turnover=total_turnover,
            total_slippage=total_slippage,
            total_costs=total_costs,
        )

        # Multi-dimensional breakdowns
        by_stock = BreakdownEngine.break_down_by_stock(completed_trades)
        by_day = BreakdownEngine.break_down_by_day(completed_trades)
        by_month = BreakdownEngine.break_down_by_month(completed_trades)
        by_regime = BreakdownEngine.break_down_by_regime(completed_trades)
        by_direction = BreakdownEngine.break_down_by_direction(completed_trades)
        by_entry_time = BreakdownEngine.break_down_by_entry_time(completed_trades)
        by_exit_reason = BreakdownEngine.break_down_by_exit_reason(completed_trades)

        return ComprehensiveReport(
            initial_capital=round(initial_capital, 2),
            final_equity=round(final_equity, 2),
            returns=returns,
            pnl=pnl,
            drawdown=drawdown,
            trade_stats=trade_stats,
            risk_adjusted=risk_adj,
            execution=execution,
            by_stock=by_stock,
            by_day=by_day,
            by_month=by_month,
            by_regime=by_regime,
            by_direction=by_direction,
            by_entry_time=by_entry_time,
            by_exit_reason=by_exit_reason,
        )

    @staticmethod
    def to_json(report: ComprehensiveReport, indent: int = 2) -> str:
        """Converts report into machine-readable JSON string."""
        return json.dumps(report.to_dict(), indent=indent)

    @staticmethod
    def to_csv(report: ComprehensiveReport, completed_trades: List[CompletedTrade]) -> Dict[str, str]:
        """
        Generates CSV outputs for:
        - trade_log.csv
        - breakdowns_stock.csv
        - breakdowns_daily.csv
        """
        csv_files: Dict[str, str] = {}

        # 1. Trade Log CSV
        buf_trades = io.StringIO()
        writer_trades = csv.writer(buf_trades)
        writer_trades.writerow([
            "TradeID", "Symbol", "Side", "Quantity", "EntryPrice", "ExitPrice",
            "EntryTime", "ExitTime", "GrossPnL", "TransactionCosts", "Slippage",
            "NetPnL", "ExitReason", "MarketRegime"
        ])
        for t in completed_trades:
            writer_trades.writerow([
                t.trade_id, t.symbol, t.side.value if hasattr(t.side, "value") else str(t.side),
                t.quantity, t.entry_price, t.exit_price,
                t.entry_time.isoformat(), t.exit_time.isoformat(),
                t.gross_pnl, t.transaction_costs, t.slippage,
                t.net_pnl, t.exit_reason or "", getattr(t, "market_regime", "") or ""
            ])
        csv_files["trade_log.csv"] = buf_trades.getvalue()

        # 2. Stock Breakdown CSV
        buf_stock = io.StringIO()
        writer_stock = csv.writer(buf_stock)
        writer_stock.writerow(["Symbol", "Trades", "Wins", "Losses", "WinRate", "GrossPnL", "Costs", "NetPnL", "ProfitFactor"])
        for b in report.by_stock:
            writer_stock.writerow([
                b.group_key, b.trades_count, b.winning_trades, b.losing_trades,
                b.win_rate, b.gross_pnl, b.transaction_costs, b.net_pnl, b.profit_factor
            ])
        csv_files["breakdowns_stock.csv"] = buf_stock.getvalue()

        # 3. Daily Breakdown CSV
        buf_day = io.StringIO()
        writer_day = csv.writer(buf_day)
        writer_day.writerow(["Date", "Trades", "Wins", "Losses", "WinRate", "GrossPnL", "Costs", "NetPnL", "ProfitFactor"])
        for b in report.by_day:
            writer_day.writerow([
                b.group_key, b.trades_count, b.winning_trades, b.losing_trades,
                b.win_rate, b.gross_pnl, b.transaction_costs, b.net_pnl, b.profit_factor
            ])
        csv_files["breakdowns_daily.csv"] = buf_day.getvalue()

        return csv_files

    @staticmethod
    def to_markdown(report: ComprehensiveReport) -> str:
        """Generates structured, human-readable Markdown performance summary."""
        lines: List[str] = [
            "# Strategy Performance & Attribution Report",
            "",
            "## Executive Summary",
            f"- **Initial Capital**: ₹{report.initial_capital:,.2f}",
            f"- **Final Equity**: ₹{report.final_equity:,.2f}",
            f"- **Net P&L**: ₹{report.pnl.net_pnl:,.2f} ({report.returns.total_return_pct:+.2f}%)",
            f"- **CAGR**: {report.returns.cagr_pct:.2f}%",
            f"- **Max Drawdown**: ₹{report.drawdown.max_drawdown_amount:,.2f} ({report.drawdown.max_drawdown_pct:.2f}%)",
            f"- **Sharpe Ratio**: {report.risk_adjusted.sharpe_ratio:.2f}",
            f"- **Profit Factor**: {report.pnl.profit_factor}",
            f"- **Win Rate**: {report.pnl.win_rate * 100:.1f}% ({report.trade_stats.winning_trades}W / {report.trade_stats.losing_trades}L)",
            f"- **Expectancy**: ₹{report.pnl.expectancy:.2f} / trade",
            "",
            "## Trade Statistics",
            f"- **Total Trades**: {report.trade_stats.total_trades}",
            f"- **Average Winner**: ₹{report.pnl.avg_winner:,.2f}",
            f"- **Average Loser**: ₹{report.pnl.avg_loser:,.2f}",
            f"- **Win/Loss Payoff Ratio**: {report.pnl.payoff_ratio:.2f}",
            f"- **Max Winning Streak**: {report.trade_stats.max_consecutive_wins}",
            f"- **Max Losing Streak**: {report.trade_stats.max_consecutive_losses}",
            f"- **Average R-Multiple**: {report.trade_stats.average_r:.2f}R",
            f"- **Avg Holding Duration**: {report.trade_stats.avg_holding_duration_mins:.1f} mins",
            "",
            "## Execution & Frictional Costs",
            f"- **Turnover**: ₹{report.execution.turnover:,.2f}",
            f"- **Transaction Costs**: ₹{report.execution.transaction_costs:,.2f} ({report.execution.costs_as_pct_of_turnover:.4f}% of turnover)",
            f"- **Execution Slippage**: ₹{report.execution.slippage:,.2f} ({report.execution.slippage_bps:.2f} bps)",
            "",
            "## Performance Breakdown by Stock",
            "| Symbol | Trades | Win Rate | Gross PnL | Costs | Net PnL | Profit Factor |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        for b in report.by_stock:
            lines.append(
                f"| {b.group_key} | {b.trades_count} | {b.win_rate*100:.1f}% | ₹{b.gross_pnl:,.2f} | ₹{b.transaction_costs:,.2f} | ₹{b.net_pnl:,.2f} | {b.profit_factor} |"
            )

        lines.extend([
            "",
            "## Performance Breakdown by Direction (Long vs Short)",
            "| Direction | Trades | Win Rate | Gross PnL | Net PnL | Profit Factor |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for b in report.by_direction:
            lines.append(
                f"| {b.group_key} | {b.trades_count} | {b.win_rate*100:.1f}% | ₹{b.gross_pnl:,.2f} | ₹{b.net_pnl:,.2f} | {b.profit_factor} |"
            )

        lines.extend([
            "",
            "## Performance Breakdown by Exit Reason",
            "| Exit Reason | Trades | Win Rate | Net PnL | Profit Factor |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for b in report.by_exit_reason:
            lines.append(
                f"| {b.group_key} | {b.trades_count} | {b.win_rate*100:.1f}% | ₹{b.net_pnl:,.2f} | {b.profit_factor} |"
            )

        return "\n".join(lines)
