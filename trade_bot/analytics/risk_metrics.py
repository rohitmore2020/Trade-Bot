"""
Risk-Adjusted Return Metrics Calculator (Sharpe, Sortino, Calmar).
"""

from __future__ import annotations

from datetime import date
import math
from typing import List, Tuple

from trade_bot.analytics.models import RiskMetrics


class RiskMetricsCalculator:
    """
    Computes Sharpe, Sortino, and Calmar ratios.
    """

    @staticmethod
    def calculate(
        daily_snapshots: List[Tuple[date, float]],
        cagr_pct: float,
        max_drawdown_pct: float,
        annual_risk_free_rate: float = 0.06,  # 6% Indian T-bill rate
    ) -> RiskMetrics:
        """Computes risk-adjusted metrics."""
        if not daily_snapshots or len(daily_snapshots) < 2:
            return RiskMetrics(
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                calmar_ratio=0.0,
            )

        daily_returns: List[float] = []
        for i in range(1, len(daily_snapshots)):
            prev_eq = daily_snapshots[i - 1][1]
            curr_eq = daily_snapshots[i][1]
            if prev_eq > 0.0:
                daily_returns.append((curr_eq - prev_eq) / prev_eq)

        if len(daily_returns) < 2:
            return RiskMetrics(
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                calmar_ratio=0.0,
            )

        n = len(daily_returns)
        mean_ret = sum(daily_returns) / n
        daily_rf = annual_risk_free_rate / 252.0

        # Total variance for Sharpe
        total_var = sum((r - mean_ret) ** 2 for r in daily_returns) / (n - 1)
        total_std = math.sqrt(max(0.0, total_var))

        sharpe = round(((mean_ret - daily_rf) / total_std) * math.sqrt(252.0), 4) if total_std > 1e-8 else 0.0

        # Downside variance for Sortino (returns below risk-free rate)
        downside_diffs = [min(0.0, r - daily_rf) for r in daily_returns]
        downside_var = sum(d ** 2 for d in downside_diffs) / n
        downside_std = math.sqrt(max(0.0, downside_var))

        sortino = round(((mean_ret - daily_rf) / downside_std) * math.sqrt(252.0), 4) if downside_std > 1e-8 else 0.0

        # Calmar Ratio: CAGR % / Max Drawdown %
        calmar = round(cagr_pct / max_drawdown_pct, 4) if max_drawdown_pct > 0.0 else 0.0

        return RiskMetrics(
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
        )
