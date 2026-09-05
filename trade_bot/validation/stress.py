"""
Frictional Stress and Stock Concentration Testing Engine.

Evaluates strategy survival under amplified statutory fees, elevated execution slippage,
and verifies absence of single-stock profit concentration.
"""

from __future__ import annotations

from typing import Dict, List

from trade_bot.portfolio.models import CompletedTrade
from trade_bot.validation.models import ExperimentSummary, StressTestResult


class StressTestEngine:
    """
    Simulates friction degradation and assesses concentration vulnerability.
    """

    @classmethod
    def evaluate_stress(
        cls,
        base_trades: List[CompletedTrade],
        cost_multipliers: List[float] = [1.0, 1.25, 1.50, 2.0],
        slippage_multipliers: List[float] = [0.0, 1.0, 2.0, 3.0],
    ) -> StressTestResult:
        """
        Runs analytical friction stress testing over completed trade set.
        """
        gross_pnl = sum(t.gross_pnl for t in base_trades)
        base_costs = sum(t.transaction_costs for t in base_trades)
        base_slippage = sum(t.slippage for t in base_trades)
        n_trades = len(base_trades)

        cost_summaries: Dict[str, ExperimentSummary] = {}
        for m in cost_multipliers:
            scaled_costs = base_costs * m
            net_pnl = round(gross_pnl - scaled_costs - base_slippage, 2)
            gross_wins = sum(t.gross_pnl for t in base_trades if t.gross_pnl > 0)
            gross_losses = sum(abs(t.gross_pnl) for t in base_trades if t.gross_pnl < 0)
            pf = round(gross_wins / gross_losses, 4) if gross_losses > 0 else (float("inf") if gross_wins > 0 else 0.0)

            cost_summaries[f"costs_{m:.2f}x"] = ExperimentSummary(
                experiment_name=f"Cost Stress {m:.2f}x",
                dataset_period="Full Period",
                strategy_version="VWAP_ORB_V1",
                parameters={"cost_multiplier": m},
                number_of_trades=n_trades,
                profit_factor=pf,
                expectancy=round(net_pnl / n_trades, 2) if n_trades > 0 else 0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                win_rate=round(sum(1 for t in base_trades if (t.gross_pnl - t.transaction_costs * m - t.slippage) > 0) / n_trades, 4) if n_trades > 0 else 0.0,
                max_losing_streak=0,
                net_pnl=net_pnl,
            )

        slippage_summaries: Dict[str, ExperimentSummary] = {}
        for sm in slippage_multipliers:
            scaled_slip = base_slippage * sm
            net_pnl = round(gross_pnl - base_costs - scaled_slip, 2)
            gross_wins = sum(t.gross_pnl for t in base_trades if t.gross_pnl > 0)
            gross_losses = sum(abs(t.gross_pnl) for t in base_trades if t.gross_pnl < 0)
            pf = round(gross_wins / gross_losses, 4) if gross_losses > 0 else (float("inf") if gross_wins > 0 else 0.0)

            slippage_summaries[f"slippage_{sm:.2f}x"] = ExperimentSummary(
                experiment_name=f"Slippage Stress {sm:.2f}x",
                dataset_period="Full Period",
                strategy_version="VWAP_ORB_V1",
                parameters={"slippage_multiplier": sm},
                number_of_trades=n_trades,
                profit_factor=pf,
                expectancy=round(net_pnl / n_trades, 2) if n_trades > 0 else 0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                win_rate=round(sum(1 for t in base_trades if (t.gross_pnl - t.transaction_costs - t.slippage * sm) > 0) / n_trades, 4) if n_trades > 0 else 0.0,
                max_losing_streak=0,
                net_pnl=net_pnl,
            )

        # Cost break-even multiplier: (gross_pnl - slippage) / base_costs
        available_margin_for_costs = gross_pnl - base_slippage
        cost_be_mult = round(available_margin_for_costs / base_costs, 2) if base_costs > 0 else float("inf")

        # Slippage break-even multiplier: (gross_pnl - base_costs) / base_slippage
        available_margin_for_slip = gross_pnl - base_costs
        slip_be_mult = round(available_margin_for_slip / base_slippage, 2) if base_slippage > 0 else float("inf")

        # Stock PnL concentration
        stock_pnls: Dict[str, float] = {}
        for t in base_trades:
            stock_pnls[t.symbol] = round(stock_pnls.get(t.symbol, 0.0) + t.net_pnl, 2)

        total_net = sum(stock_pnls.values())
        top_stock_val = max(stock_pnls.values()) if stock_pnls else 0.0
        top_conc_pct = round((top_stock_val / total_net) * 100.0, 2) if total_net > 0 else 0.0

        return StressTestResult(
            cost_stress_summaries=cost_summaries,
            slippage_stress_summaries=slippage_summaries,
            stock_pnl_distribution=stock_pnls,
            top_stock_concentration_pct=top_conc_pct,
            cost_breakeven_multiplier=cost_be_mult,
            slippage_breakeven_multiplier=slip_be_mult,
        )
