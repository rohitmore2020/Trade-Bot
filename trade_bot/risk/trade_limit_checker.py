"""
Trade and Position Limit Checker.

Enforces:
1. Maximum simultaneous open positions limit (3 concurrent positions)
2. Maximum trades per day limit (6 trades per day)

Zero external infrastructure dependencies; pure domain logic.
"""

from __future__ import annotations

from typing import Optional

from trade_bot.risk.models import RiskAssessmentContext, RiskParameters, TradeProposal


class TradeLimitChecker:
    """
    Validates daily execution counts and simultaneous position limits.
    """

    def __init__(self, params: Optional[RiskParameters] = None) -> None:
        self.params = params or RiskParameters()

    def check(
        self,
        proposal: TradeProposal,
        context: RiskAssessmentContext,
    ) -> tuple[bool, Optional[str]]:
        """
        Validates trade limits.
        Returns (True, None) if within limits, otherwise (False, rejection_reason).
        """
        # Check 1: Maximum Daily Trades
        if context.daily_executed_trades >= self.params.max_daily_trades:
            return False, (
                f"Maximum daily trades limit reached: "
                f"{context.daily_executed_trades} >= {self.params.max_daily_trades}"
            )

        # Check 2: Maximum Simultaneous Open Positions
        # Count non-flat active positions
        open_positions_count = sum(1 for p in context.current_positions.values() if not p.is_flat)
        existing_pos = context.current_positions.get(proposal.symbol)
        is_new_symbol = existing_pos is None or existing_pos.is_flat

        if is_new_symbol and open_positions_count >= self.params.max_open_positions:
            return False, (
                f"Maximum simultaneous positions limit reached: "
                f"{open_positions_count} >= {self.params.max_open_positions}"
            )

        return True, None
