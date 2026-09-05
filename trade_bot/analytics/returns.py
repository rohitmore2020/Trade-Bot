"""
Returns and Volatility Analytics Calculator.
"""

from __future__ import annotations

from datetime import date
import math
from typing import List, Optional, Tuple

from trade_bot.analytics.models import ReturnMetrics


class ReturnsCalculator:
    """
    Computes total return, CAGR, daily return series, and annualized volatility.
    """

    @staticmethod
    def calculate(
        initial_capital: float,
        final_equity: float,
        daily_snapshots: Optional[List[Tuple[date, float]]] = None,
        calendar_days: Optional[int] = None,
    ) -> ReturnMetrics:
        """
        Computes return and volatility metrics.
        """
        if initial_capital <= 0.0:
            return ReturnMetrics(
                total_return_pct=0.0,
                cagr_pct=0.0,
                daily_volatility_pct=0.0,
                annualized_volatility_pct=0.0,
            )

        total_return_pct = round(((final_equity - initial_capital) / initial_capital) * 100.0, 4)

        # CAGR calculation
        cagr_pct = total_return_pct
        if calendar_days and calendar_days > 0 and final_equity > 0.0:
            years = calendar_days / 365.25
            if years >= (1.0 / 12.0):  # At least ~1 month for meaningful CAGR
                cagr_pct = round((((final_equity / initial_capital) ** (1.0 / years)) - 1.0) * 100.0, 4)

        # Daily returns and volatility
        daily_vol_pct = 0.0
        annualized_vol_pct = 0.0

        if daily_snapshots and len(daily_snapshots) >= 2:
            daily_returns: List[float] = []
            for i in range(1, len(daily_snapshots)):
                prev_eq = daily_snapshots[i - 1][1]
                curr_eq = daily_snapshots[i][1]
                if prev_eq > 0.0:
                    ret = (curr_eq - prev_eq) / prev_eq
                    daily_returns.append(ret)

            if len(daily_returns) >= 2:
                n = len(daily_returns)
                mean_ret = sum(daily_returns) / n
                variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (n - 1)
                daily_vol = math.sqrt(max(0.0, variance))
                daily_vol_pct = round(daily_vol * 100.0, 4)
                annualized_vol_pct = round(daily_vol * math.sqrt(252.0) * 100.0, 4)

        return ReturnMetrics(
            total_return_pct=total_return_pct,
            cagr_pct=cagr_pct,
            daily_volatility_pct=daily_vol_pct,
            annualized_volatility_pct=annualized_vol_pct,
        )
