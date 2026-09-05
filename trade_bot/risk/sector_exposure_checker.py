"""
Sector Exposure and Concentration Checker.

Enforces:
- Maximum sector concentration limit (40.0% of equity)
- Conservative fail-safe rejection when sector mapping is missing

Zero external infrastructure dependencies; pure domain logic.
"""

from __future__ import annotations

from typing import Optional

from trade_bot.risk.models import RiskAssessmentContext, RiskParameters, TradeProposal


class SectorExposureChecker:
    """
    Validates portfolio exposure against sector concentration limits.
    """

    def __init__(self, params: Optional[RiskParameters] = None) -> None:
        self.params = params or RiskParameters()

    def get_sector(self, symbol: str, proposal: TradeProposal, context: RiskAssessmentContext) -> Optional[str]:
        """Resolves sector from proposal or context map."""
        if proposal.sector:
            return proposal.sector.upper()
        if symbol in context.symbol_sector_map:
            return context.symbol_sector_map[symbol].upper()
        return None

    def check(
        self,
        proposal: TradeProposal,
        quantity: int,
        context: RiskAssessmentContext,
    ) -> tuple[bool, Optional[str]]:
        """
        Validates sector concentration.
        Returns (True, None) if compliant, otherwise (False, rejection_reason).
        """
        if quantity <= 0:
            return False, "Cannot check sector exposure for zero or negative quantity"

        sector = self.get_sector(proposal.symbol, proposal, context)
        # Fail-safe: Missing sector information must reject the trade
        if not sector:
            return False, (
                f"Fail-Safe rejection: Missing sector classification for symbol '{proposal.symbol}'"
            )

        max_sector_notional = round(context.equity * self.params.max_sector_exposure_pct, 2)

        # Calculate current exposure in this sector
        current_sector_exposure = 0.0
        for sym, pos in context.current_positions.items():
            if pos.is_flat:
                continue
            pos_sector = context.symbol_sector_map.get(sym.upper()) or (
                proposal.sector.upper() if sym.upper() == proposal.symbol.upper() else None
            )
            if pos_sector == sector:
                pos_price = pos.last_price if pos.last_price > 0 else pos.average_price
                current_sector_exposure += abs(pos.quantity) * pos_price

        proposed_trade_notional = round(proposal.entry_price * quantity, 2)
        total_sector_exposure = round(current_sector_exposure + proposed_trade_notional, 2)

        if total_sector_exposure > max_sector_notional:
            return False, (
                f"Sector exposure for '{sector}' ({total_sector_exposure:.2f}) exceeds "
                f"maximum limit {max_sector_notional:.2f} ({self.params.max_sector_exposure_pct * 100:.1f}%)"
            )

        return True, None
