"""
Profit and Loss Analytics Calculator.
"""

from __future__ import annotations

from typing import List

from trade_bot.analytics.models import PnLMetrics
from trade_bot.portfolio.models import CompletedTrade


class PnLAnalyticsCalculator:
    """
    Computes statistical and absolute PnL attribution across completed trades.
    """

    @staticmethod
    def calculate(completed_trades: List[CompletedTrade]) -> PnLMetrics:
        """Computes comprehensive PnL metrics."""
        total_trades = len(completed_trades)
        if total_trades == 0:
            return PnLMetrics(
                gross_pnl=0.0,
                net_pnl=0.0,
                profit_factor=0.0,
                expectancy=0.0,
                win_rate=0.0,
                avg_winner=0.0,
                avg_loser=0.0,
                payoff_ratio=0.0,
            )

        gross_pnl = round(sum(t.gross_pnl for t in completed_trades), 2)
        net_pnl = round(sum(t.net_pnl for t in completed_trades), 2)

        winning_trades = [t.net_pnl for t in completed_trades if t.net_pnl > 0.0]
        losing_trades = [t.net_pnl for t in completed_trades if t.net_pnl < 0.0]

        n_wins = len(winning_trades)
        n_losses = len(losing_trades)
        win_rate = round(n_wins / total_trades, 4)
        expectancy = round(net_pnl / total_trades, 2)

        gross_wins = sum(t.gross_pnl for t in completed_trades if t.gross_pnl > 0.0)
        gross_losses = sum(abs(t.gross_pnl) for t in completed_trades if t.gross_pnl < 0.0)

        if gross_losses > 0.0:
            profit_factor = round(gross_wins / gross_losses, 4)
        elif gross_wins > 0.0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        avg_winner = round(sum(winning_trades) / n_wins, 2) if n_wins > 0 else 0.0
        avg_loser = round(sum(losing_trades) / n_losses, 2) if n_losses > 0 else 0.0

        payoff_ratio = round(avg_winner / abs(avg_loser), 4) if abs(avg_loser) > 0.0 else (float("inf") if avg_winner > 0.0 else 0.0)

        return PnLMetrics(
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            profit_factor=profit_factor,
            expectancy=expectancy,
            win_rate=win_rate,
            avg_winner=avg_winner,
            avg_loser=avg_loser,
            payoff_ratio=payoff_ratio,
        )
