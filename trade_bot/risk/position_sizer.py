"""
Deterministic Position Sizer.

Calculates maximum permitted quantity based on:
1. 0.5% Fixed fractional equity risk budget
2. 20.0% Maximum capital per trade cap
3. Available cash liquidity cap
4. Lot-size constraints and integer share rounding
5. Macro and volatility regime reductions

Zero external infrastructure dependencies; pure domain computation.
"""

from __future__ import annotations

from typing import Optional

from trade_bot.domain.enums import MarketRegime
from trade_bot.indicators.vix_filter import VIXRegime
from trade_bot.risk.models import RiskAssessmentContext, RiskParameters, TradeProposal


class PositionSizer:
    """
    Computes deterministic position sizing with conservative fail-safes.
    """

    def __init__(self, params: Optional[RiskParameters] = None) -> None:
        self.params = params or RiskParameters()

    def calculate_quantity(
        self,
        proposal: TradeProposal,
        context: RiskAssessmentContext,
    ) -> int:
        """
        Determines the approved integer quantity for a trade proposal.
        Returns 0 if inputs are invalid or risk constraints cannot be satisfied.
        """
        # Fail-Safe 1: Price and Stop-Loss validity
        if proposal.entry_price <= 0.0 or proposal.stop_loss_price <= 0.0:
            return 0

        # Fail-Safe 2: Equity and Cash validity
        if context.equity <= 0.0 or context.available_cash <= 0.0:
            return 0

        # Fail-Safe 3: Zero or negative stop distance
        risk_per_share = round(abs(proposal.entry_price - proposal.stop_loss_price), 4)
        if risk_per_share <= 0.0:
            return 0

        # Constraint 1: Risk Budget (0.5% of Equity)
        risk_budget = context.equity * self.params.max_risk_per_trade_pct
        qty_risk = int(risk_budget / risk_per_share)

        # Constraint 2: Maximum Capital per Trade (20% of Equity)
        max_notional = context.equity * self.params.max_capital_per_trade_pct
        qty_capital = int(max_notional / proposal.entry_price)

        # Constraint 3: Available Cash
        qty_cash = int(context.available_cash / proposal.entry_price)

        # Base Quantity is the strictest bound
        raw_qty = min(qty_risk, qty_capital, qty_cash)
        if raw_qty <= 0:
            return 0

        # Constraint 4: Volatility Regime Adjustments
        if context.vix_regime == VIXRegime.ELEVATED:
            raw_qty = int(raw_qty * self.params.elevated_vix_multiplier)
        elif context.vix_regime == VIXRegime.EXTREME:
            raw_qty = int(raw_qty * self.params.extreme_vix_multiplier)

        # Constraint 5: Macro Regime Adjustments
        if context.market_regime == MarketRegime.NEUTRAL:
            raw_qty = 0

        # Constraint 6: Lot Size Alignment
        lot_size = max(1, proposal.lot_size)
        final_qty = (raw_qty // lot_size) * lot_size

        # Optional: Cap by requested quantity if provided
        if proposal.requested_quantity is not None and proposal.requested_quantity > 0:
            final_qty = min(final_qty, proposal.requested_quantity)
            final_qty = (final_qty // lot_size) * lot_size

        return max(0, final_qty)
