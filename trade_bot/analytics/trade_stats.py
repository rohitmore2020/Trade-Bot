"""
Trade Distribution and Streak Statistics Calculator.
"""

from __future__ import annotations

from typing import List

from trade_bot.analytics.models import TradeStatsMetrics
from trade_bot.portfolio.models import CompletedTrade


class TradeStatsCalculator:
    """
    Computes trade count, streak analysis, holding duration, and R-multiples.
    """

    @staticmethod
    def calculate(completed_trades: List[CompletedTrade]) -> TradeStatsMetrics:
        """Computes trade stats and streaks."""
        total_trades = len(completed_trades)
        if total_trades == 0:
            return TradeStatsMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                break_even_trades=0,
                max_consecutive_wins=0,
                max_consecutive_losses=0,
                avg_holding_duration_mins=0.0,
                average_r=0.0,
            )

        winning_trades = sum(1 for t in completed_trades if t.net_pnl > 0.0)
        losing_trades = sum(1 for t in completed_trades if t.net_pnl < 0.0)
        break_even_trades = sum(1 for t in completed_trades if t.net_pnl == 0.0)

        # Streaks
        current_wins = 0
        max_wins = 0
        current_losses = 0
        max_losses = 0

        for t in completed_trades:
            if t.net_pnl > 0.0:
                current_wins += 1
                max_wins = max(max_wins, current_wins)
                current_losses = 0
            elif t.net_pnl < 0.0:
                current_losses += 1
                max_losses = max(max_losses, current_losses)
                current_wins = 0
            else:
                current_wins = 0
                current_losses = 0

        # Holding duration
        holding_mins = [
            max(0.0, (t.exit_time - t.entry_time).total_seconds() / 60.0)
            for t in completed_trades
        ]
        avg_holding_mins = round(sum(holding_mins) / len(holding_mins), 2) if holding_mins else 0.0

        # Average R-multiple
        r_multiples: List[float] = []
        for t in completed_trades:
            # Risk unit based on 1% entry price * qty or price diff
            risk_unit = max(1.0, t.entry_price * 0.01 * t.quantity)
            r_multiples.append(t.net_pnl / risk_unit)

        avg_r = round(sum(r_multiples) / len(r_multiples), 4) if r_multiples else 0.0

        return TradeStatsMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            break_even_trades=break_even_trades,
            max_consecutive_wins=max_wins,
            max_consecutive_losses=max_losses,
            avg_holding_duration_mins=avg_holding_mins,
            average_r=avg_r,
        )
