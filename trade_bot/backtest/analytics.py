"""
Backtest Analytics and Metrics Engine.

Calculates comprehensive performance, risk, and attribution metrics
from portfolio completed trades, fills, and daily equity curves.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import math
from typing import Dict, List, Optional, Tuple

from trade_bot.backtest.models import BacktestMetrics, DailyPnLSummary
from trade_bot.portfolio.models import CompletedTrade, Fill


class BacktestAnalytics:
    """
    Computes deterministic statistical and financial performance metrics.
    """

    @staticmethod
    def compute_metrics(
        initial_capital: float,
        completed_trades: List[CompletedTrade],
        daily_snapshots: List[DailyPnLSummary],
        equity_curve: List[Tuple[datetime, float]],
        total_turnover: float,
        peak_exposure: float,
        average_exposure: float,
        total_slippage: float = 0.0,
        risk_free_rate_annual: float = 0.06,  # 6% Indian MIBOR/T-bill proxy
    ) -> BacktestMetrics:
        """
        Computes all required performance and risk metrics.
        """
        total_trades = len(completed_trades)
        if total_trades == 0:
            return BacktestMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                break_even_trades=0,
                gross_pnl=0.0,
                transaction_costs=0.0,
                slippage=0.0,
                net_pnl=0.0,
                profit_factor=0.0,
                expectancy=0.0,
                win_rate=0.0,
                max_drawdown=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                average_r=0.0,
                maximum_losing_streak=0,
                maximum_winning_streak=0,
                peak_exposure=0.0,
                average_exposure=0.0,
                turnover=round(total_turnover, 2),
            )

        winning_trades = sum(1 for t in completed_trades if t.net_pnl > 0.0)
        losing_trades = sum(1 for t in completed_trades if t.net_pnl < 0.0)
        break_even_trades = sum(1 for t in completed_trades if t.net_pnl == 0.0)

        gross_pnl = sum(t.gross_pnl for t in completed_trades)
        transaction_costs = sum(t.transaction_costs for t in completed_trades)
        net_pnl = sum(t.net_pnl for t in completed_trades)

        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        expectancy = net_pnl / total_trades if total_trades > 0 else 0.0

        # Profit Factor
        total_gross_wins = sum(t.gross_pnl for t in completed_trades if t.gross_pnl > 0.0)
        total_gross_losses = sum(abs(t.gross_pnl) for t in completed_trades if t.gross_pnl < 0.0)
        if total_gross_losses > 0.0:
            profit_factor = total_gross_wins / total_gross_losses
        elif total_gross_wins > 0.0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        # Average R-Multiple
        r_multiples: List[float] = []
        for t in completed_trades:
            # Estimate initial risk per share
            price_delta = abs(t.entry_price - t.exit_price)
            # If trade has positive PnL, R is positive
            if t.quantity > 0:
                # Default baseline 1.5 ATR risk estimate or entry risk
                estimated_risk = max(1.0, t.entry_price * 0.01 * t.quantity)
                r_multiples.append(t.net_pnl / estimated_risk)
        average_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0

        # Streaks
        current_win_streak = 0
        max_win_streak = 0
        current_loss_streak = 0
        max_loss_streak = 0

        for t in completed_trades:
            if t.net_pnl > 0.0:
                current_win_streak += 1
                max_win_streak = max(max_win_streak, current_win_streak)
                current_loss_streak = 0
            elif t.net_pnl < 0.0:
                current_loss_streak += 1
                max_loss_streak = max(max_loss_streak, current_loss_streak)
                current_win_streak = 0
            else:
                current_win_streak = 0
                current_loss_streak = 0

        # Max Drawdown from Equity Curve
        max_dd_amt = 0.0
        max_dd_pct = 0.0
        if equity_curve:
            peak = equity_curve[0][1]
            for _, eq in equity_curve:
                if eq > peak:
                    peak = eq
                dd = peak - eq
                dd_pct = (dd / peak) if peak > 0.0 else 0.0
                if dd > max_dd_amt:
                    max_dd_amt = dd
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct

        # Annualized Sharpe Ratio from Daily Returns
        sharpe_ratio = 0.0
        if len(daily_snapshots) >= 2:
            daily_returns = [d.return_pct for d in daily_snapshots]
            n_days = len(daily_returns)
            mean_return = sum(daily_returns) / n_days
            variance = sum((r - mean_return) ** 2 for r in daily_returns) / (n_days - 1)
            std_dev = math.sqrt(variance)

            # Daily risk-free rate from annual rate (252 trading days)
            daily_rf = risk_free_rate_annual / 252.0

            if std_dev > 1e-8:
                sharpe_ratio = ((mean_return - daily_rf) / std_dev) * math.sqrt(252.0)

        return BacktestMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            break_even_trades=break_even_trades,
            gross_pnl=round(gross_pnl, 2),
            transaction_costs=round(transaction_costs, 2),
            slippage=round(total_slippage, 2),
            net_pnl=round(net_pnl, 2),
            profit_factor=round(profit_factor, 4),
            expectancy=round(expectancy, 2),
            win_rate=round(win_rate, 4),
            max_drawdown=round(max_dd_amt, 2),
            max_drawdown_pct=round(max_dd_pct, 4),
            sharpe_ratio=round(sharpe_ratio, 4),
            average_r=round(average_r, 4),
            maximum_losing_streak=max_loss_streak,
            maximum_winning_streak=max_win_streak,
            peak_exposure=round(peak_exposure, 2),
            average_exposure=round(average_exposure, 2),
            turnover=round(total_turnover, 2),
        )

    @staticmethod
    def aggregate_daily_pnl(
        completed_trades: List[CompletedTrade],
        equity_snapshots_by_date: Dict[date, List[float]],
        initial_capital: float,
    ) -> List[DailyPnLSummary]:
        """Groups trading results by calendar day into daily performance records."""
        trades_by_date: Dict[date, List[CompletedTrade]] = defaultdict(list)
        for t in completed_trades:
            trades_by_date[t.exit_time.date()].append(t)

        all_dates = sorted(set(list(equity_snapshots_by_date.keys()) + list(trades_by_date.keys())))
        summaries: List[DailyPnLSummary] = []
        rolling_equity = initial_capital

        for d in all_dates:
            day_trades = trades_by_date.get(d, [])
            day_gross = sum(t.gross_pnl for t in day_trades)
            day_costs = sum(t.transaction_costs for t in day_trades)
            day_net = sum(t.net_pnl for t in day_trades)

            day_start_equity = rolling_equity
            rolling_equity += day_net
            day_end_equity = rolling_equity

            day_return = (day_net / day_start_equity) if day_start_equity > 0.0 else 0.0
            day_wins = sum(1 for t in day_trades if t.net_pnl > 0.0)
            day_losses = sum(1 for t in day_trades if t.net_pnl < 0.0)

            # Max exposure during day
            day_equity_points = equity_snapshots_by_date.get(d, [day_end_equity])
            max_exp = max(day_equity_points) if day_equity_points else 0.0

            summaries.append(
                DailyPnLSummary(
                    trading_date=d,
                    trades_count=len(day_trades),
                    winning_trades=day_wins,
                    losing_trades=day_losses,
                    gross_pnl=round(day_gross, 2),
                    transaction_costs=round(day_costs, 2),
                    slippage=0.0,
                    net_pnl=round(day_net, 2),
                    starting_equity=round(day_start_equity, 2),
                    ending_equity=round(day_end_equity, 2),
                    return_pct=round(day_return, 4),
                    max_exposure=round(max_exp, 2),
                )
            )

        return summaries
