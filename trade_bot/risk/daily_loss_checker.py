"""
Daily Loss and Circuit Breaker Checker.

Enforces:
- Maximum daily loss limit (2.0% of equity)
- Circuit breaker trip causing immediate trading halt

Zero external infrastructure dependencies; pure domain logic.
"""

from __future__ import annotations

from typing import Optional

from trade_bot.risk.models import RiskAssessmentContext, RiskParameters


class DailyLossChecker:
    """
    Evaluates intraday loss against the 2.0% equity circuit breaker.
    """

    def __init__(self, params: Optional[RiskParameters] = None) -> None:
        self.params = params or RiskParameters()

    def check(self, context: RiskAssessmentContext) -> tuple[bool, Optional[str]]:
        """
        Validates cumulative daily loss against allowable limit.
        Returns (True, None) if within limits, otherwise (False, rejection_reason).
        """
        if context.equity <= 0.0:
            return False, "Invalid equity: Account equity must be strictly positive"

        daily_pnl = context.daily_realized_pnl + context.daily_unrealized_pnl
        max_allowable_loss = round(context.equity * self.params.max_daily_loss_pct, 2)

        if daily_pnl <= -max_allowable_loss:
            return False, (
                f"Daily loss limit breached: Current daily PnL {daily_pnl:.2f} "
                f"breaches limit of -{max_allowable_loss:.2f} ({self.params.max_daily_loss_pct * 100:.1f}%)"
            )

        return True, None
