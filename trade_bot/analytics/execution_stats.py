"""
Execution, Turnover, Costs, and Slippage Analytics Calculator.
"""

from __future__ import annotations

from typing import List

from trade_bot.analytics.models import ExecutionMetrics
from trade_bot.portfolio.models import CompletedTrade


class ExecutionStatsCalculator:
    """
    Computes turnover, friction ratios, slippage basis points, and cost impact.
    """

    @staticmethod
    def calculate(
        completed_trades: List[CompletedTrade],
        total_turnover: float,
        total_slippage: float = 0.0,
        total_costs: float = 0.0,
    ) -> ExecutionMetrics:
        """Computes execution metrics."""
        costs = total_costs if total_costs > 0.0 else sum(t.transaction_costs for t in completed_trades)
        slippage = total_slippage if total_slippage > 0.0 else sum(t.slippage for t in completed_trades)
        turnover = round(total_turnover, 2)

        gross_pnl = sum(t.gross_pnl for t in completed_trades)

        # Slippage bps: (slippage / turnover) * 10,000
        slippage_bps = round((slippage / turnover) * 10000.0, 2) if turnover > 0.0 else 0.0

        # Costs % of turnover
        costs_pct_turnover = round((costs / turnover) * 100.0, 4) if turnover > 0.0 else 0.0

        # Costs % of gross pnl
        costs_pct_gross = round((costs / abs(gross_pnl)) * 100.0, 2) if abs(gross_pnl) > 0.0 else 0.0

        return ExecutionMetrics(
            turnover=turnover,
            transaction_costs=round(costs, 2),
            slippage=round(slippage, 2),
            slippage_bps=slippage_bps,
            costs_as_pct_of_turnover=costs_pct_turnover,
            costs_as_pct_of_gross_pnl=costs_pct_gross,
        )
