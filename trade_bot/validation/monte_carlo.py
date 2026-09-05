"""
Monte Carlo Trade Sequence Randomization Engine.

Evaluates trade sequence risk, tail drawdown risk, consecutive losing streaks,
and downside ruin probabilities without assumptions of normality.
"""

from __future__ import annotations

import random
from typing import List, Optional

from trade_bot.validation.models import MonteCarloSimulationResult


class MonteCarloSimulator:
    """
    Simulates thousands of synthetic equity paths through bootstrap trade sequence permutation.
    """

    @classmethod
    def simulate(
        cls,
        trade_pnls: List[float],
        initial_capital: float = 100_000.0,
        iterations: int = 1_000,
        random_seed: Optional[int] = 42,
    ) -> MonteCarloSimulationResult:
        """
        Executes N iterations of trade sequence resampling with replacement.
        """
        if not trade_pnls:
            return MonteCarloSimulationResult(
                iterations=iterations,
                initial_capital=initial_capital,
                mean_terminal_equity=initial_capital,
                median_terminal_equity=initial_capital,
                p5_terminal_equity=initial_capital,
                p25_terminal_equity=initial_capital,
                p75_terminal_equity=initial_capital,
                p95_terminal_equity=initial_capital,
                p99_terminal_equity=initial_capital,
                median_max_drawdown_pct=0.0,
                p95_max_drawdown_pct=0.0,
                worst_case_drawdown_pct=0.0,
                median_losing_streak=0,
                p95_losing_streak=0,
                max_losing_streak=0,
                probability_of_loss=0.0,
                risk_of_ruin_pct=0.0,
            )

        rng = random.Random(random_seed)
        n_trades = len(trade_pnls)

        terminal_equities: List[float] = []
        max_drawdowns_pct: List[float] = []
        max_losing_streaks: List[int] = []

        for _ in range(iterations):
            # Resample trade PnLs with replacement
            sampled_pnls = [rng.choice(trade_pnls) for _ in range(n_trades)]

            current_equity = initial_capital
            peak_equity = initial_capital
            max_dd = 0.0

            current_loss_streak = 0
            max_streak = 0

            for pnl in sampled_pnls:
                current_equity += pnl
                if current_equity > peak_equity:
                    peak_equity = current_equity

                dd = peak_equity - current_equity
                dd_pct = (dd / peak_equity) * 100.0 if peak_equity > 0.0 else 0.0
                if dd_pct > max_dd:
                    max_dd = dd_pct

                if pnl < 0.0:
                    current_loss_streak += 1
                    if current_loss_streak > max_streak:
                        max_streak = current_loss_streak
                else:
                    current_loss_streak = 0

            terminal_equities.append(round(current_equity, 2))
            max_drawdowns_pct.append(round(max_dd, 4))
            max_losing_streaks.append(max_streak)

        terminal_equities.sort()
        max_drawdowns_pct.sort()
        max_losing_streaks.sort()

        def percentile(arr: List[Any], p: float) -> Any:
            idx = int(round(p * (len(arr) - 1)))
            return arr[min(len(arr) - 1, max(0, idx))]

        mean_equity = round(sum(terminal_equities) / iterations, 2)
        median_equity = percentile(terminal_equities, 0.50)
        p5_equity = percentile(terminal_equities, 0.05)
        p25_equity = percentile(terminal_equities, 0.25)
        p75_equity = percentile(terminal_equities, 0.75)
        p95_equity = percentile(terminal_equities, 0.95)
        p99_equity = percentile(terminal_equities, 0.99)

        median_dd = percentile(max_drawdowns_pct, 0.50)
        p95_dd = percentile(max_drawdowns_pct, 0.95)
        worst_dd = max_drawdowns_pct[-1]

        median_streak = percentile(max_losing_streaks, 0.50)
        p95_streak = percentile(max_losing_streaks, 0.95)
        worst_streak = max_losing_streaks[-1]

        prob_loss = round(sum(1 for eq in terminal_equities if eq < initial_capital) / iterations * 100.0, 2)
        risk_of_ruin = round(sum(1 for dd in max_drawdowns_pct if dd >= 20.0) / iterations * 100.0, 2)

        return MonteCarloSimulationResult(
            iterations=iterations,
            initial_capital=initial_capital,
            mean_terminal_equity=mean_equity,
            median_terminal_equity=median_equity,
            p5_terminal_equity=p5_equity,
            p25_terminal_equity=p25_equity,
            p75_terminal_equity=p75_equity,
            p95_terminal_equity=p95_equity,
            p99_terminal_equity=p99_equity,
            median_max_drawdown_pct=median_dd,
            p95_max_drawdown_pct=p95_dd,
            worst_case_drawdown_pct=worst_dd,
            median_losing_streak=median_streak,
            p95_losing_streak=p95_streak,
            max_losing_streak=worst_streak,
            probability_of_loss=prob_loss,
            risk_of_ruin_pct=risk_of_ruin,
        )
