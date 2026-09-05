"""
Capital and Trade Exposure Checker.

Enforces:
1. Maximum capital per trade (20.0% of equity)
2. Maximum risk per trade (0.5% of equity)
3. Available cash liquidity verification

Zero external infrastructure dependencies; pure domain logic.
"""

from __future__ import annotations

from typing import Optional

from trade_bot.risk.models import RiskAssessmentContext, RiskParameters, TradeProposal


class CapitalExposureChecker:
    """
    Validates per-trade capital allocation and risk exposure limits.
    """

    def __init__(self, params: Optional[RiskParameters] = None) -> None:
        self.params = params or RiskParameters()

    def check(
        self,
        proposal: TradeProposal,
        quantity: int,
        context: RiskAssessmentContext,
    ) -> tuple[bool, Optional[str]]:
        """
        Validates capital and risk thresholds for a specified quantity.
        Returns (True, None) if compliant, otherwise (False, rejection_reason).
        """
        if quantity <= 0:
            return False, "Cannot approve trade with zero or negative quantity"

        notional_value = round(proposal.entry_price * quantity, 2)
        max_capital_allowed = round(context.equity * self.params.max_capital_per_trade_pct, 2)

        # 1. Capital per trade check (20% cap)
        if notional_value > max_capital_allowed:
            return False, (
                f"Capital per trade {notional_value:.2f} exceeds maximum allowed "
                f"{max_capital_allowed:.2f} ({self.params.max_capital_per_trade_pct * 100:.1f}%)"
            )

        # 2. Available cash check
        if notional_value > context.available_cash:
            return False, (
                f"Required capital {notional_value:.2f} exceeds available cash {context.available_cash:.2f}"
            )

        # 3. Maximum risk per trade check (0.5% cap)
        risk_per_share = round(abs(proposal.entry_price - proposal.stop_loss_price), 4)
        total_risk = round(risk_per_share * quantity, 2)
        max_risk_allowed = round(context.equity * self.params.max_risk_per_trade_pct, 2)

        if total_risk > (max_risk_allowed + 0.05):  # allow tiny tick rounding epsilon
            return False, (
                f"Trade risk {total_risk:.2f} exceeds maximum allowed "
                f"{max_risk_allowed:.2f} ({self.params.max_risk_per_trade_pct * 100:.1f}%)"
            )

        return True, None
