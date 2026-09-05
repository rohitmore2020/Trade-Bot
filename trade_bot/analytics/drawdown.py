"""
Drawdown Analytics Calculator.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

from trade_bot.analytics.models import DrawdownMetrics


class DrawdownCalculator:
    """
    Computes maximum drawdown, average drawdown, and underwater duration.
    """

    @staticmethod
    def calculate(
        equity_curve: List[Tuple[datetime, float]],
        initial_capital: float,
    ) -> DrawdownMetrics:
        """Computes drawdown metrics from timestamped equity series."""
        if not equity_curve:
            return DrawdownMetrics(
                max_drawdown_amount=0.0,
                max_drawdown_pct=0.0,
                avg_drawdown_pct=0.0,
                max_drawdown_duration_days=0,
            )

        peak = initial_capital
        max_dd_amt = 0.0
        max_dd_pct = 0.0
        dd_percentages: List[float] = []

        # Duration tracking
        peak_time = equity_curve[0][0]
        current_duration_days = 0
        max_duration_days = 0

        for ts, eq in equity_curve:
            if eq > peak:
                peak = eq
                peak_time = ts
            else:
                duration_days = (ts - peak_time).days
                max_duration_days = max(max_duration_days, duration_days)

            dd_amt = peak - eq
            dd_pct = (dd_amt / peak) * 100.0 if peak > 0.0 else 0.0
            dd_percentages.append(dd_pct)

            if dd_amt > max_dd_amt:
                max_dd_amt = dd_amt
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        avg_dd_pct = round(sum(dd_percentages) / len(dd_percentages), 4) if dd_percentages else 0.0

        return DrawdownMetrics(
            max_drawdown_amount=round(max_dd_amt, 2),
            max_drawdown_pct=round(max_dd_pct, 4),
            avg_drawdown_pct=avg_dd_pct,
            max_drawdown_duration_days=max_duration_days,
        )
