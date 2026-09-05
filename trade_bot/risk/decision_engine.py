"""
Pure Risk Decision Engine.

Coordinates distinct risk checkers and position sizing into a unified,
conservative, fail-safe evaluation pipeline.

Decoupled from broker adapters, HTTP requests, WebSockets, databases, and UIs.
"""

from __future__ import annotations

from typing import Dict, Optional

from trade_bot.domain.enums import RiskCheckResultStatus
from trade_bot.risk.capital_exposure_checker import CapitalExposureChecker
from trade_bot.risk.daily_loss_checker import DailyLossChecker
from trade_bot.risk.models import (
    RiskAssessmentContext,
    RiskDecisionResult,
    RiskParameters,
    TradeProposal,
)
from trade_bot.risk.position_sizer import PositionSizer
from trade_bot.risk.sector_exposure_checker import SectorExposureChecker
from trade_bot.risk.trade_limit_checker import TradeLimitChecker
from trade_bot.strategy.models import TradeIntent


class RiskDecisionEngine:
    """
    Independent Risk Decision Engine.
    Enforces conservative fail-safes and coordinates individual risk checkers.
    """

    def __init__(
        self,
        params: Optional[RiskParameters] = None,
        position_sizer: Optional[PositionSizer] = None,
        trade_limit_checker: Optional[TradeLimitChecker] = None,
        daily_loss_checker: Optional[DailyLossChecker] = None,
        capital_exposure_checker: Optional[CapitalExposureChecker] = None,
        sector_exposure_checker: Optional[SectorExposureChecker] = None,
    ) -> None:
        self.params = params or RiskParameters()
        self.position_sizer = position_sizer or PositionSizer(params=self.params)
        self.trade_limit_checker = trade_limit_checker or TradeLimitChecker(params=self.params)
        self.daily_loss_checker = daily_loss_checker or DailyLossChecker(params=self.params)
        self.capital_exposure_checker = capital_exposure_checker or CapitalExposureChecker(params=self.params)
        self.sector_exposure_checker = sector_exposure_checker or SectorExposureChecker(params=self.params)

    def evaluate_from_intent(
        self,
        intent: TradeIntent,
        context: RiskAssessmentContext,
        sector: Optional[str] = None,
        lot_size: int = 1,
    ) -> RiskDecisionResult:
        """
        Convenience adapter evaluating a Phase 8 TradeIntent domain object.
        """
        proposal = TradeProposal(
            symbol=intent.symbol,
            side=intent.side,
            entry_price=intent.proposed_entry_price,
            stop_loss_price=intent.proposed_stop_price,
            sector=sector,
            lot_size=lot_size,
            timestamp=intent.timestamp,
            metadata=dict(intent.metadata),
        )
        return self.evaluate(proposal, context)

    def evaluate(
        self,
        proposal: TradeProposal,
        context: RiskAssessmentContext,
    ) -> RiskDecisionResult:
        """
        Evaluates a TradeProposal against all approved risk limits.
        Fails fast upon first constraint violation.
        """
        checks: Dict[str, bool] = {
            "inputs_valid": False,
            "daily_loss_valid": False,
            "trade_limits_valid": False,
            "sizing_valid": False,
            "capital_exposure_valid": False,
            "sector_exposure_valid": False,
        }

        # --- FAIL-SAFE 1: Validate Basic Inputs ---
        if context is None or proposal is None:
            return RiskDecisionResult(
                status=RiskCheckResultStatus.REJECTED,
                is_approved=False,
                reason="Fail-Safe rejection: Missing proposal or context object",
                rule_name="InputValidation",
                checks=checks,
            )

        if proposal.entry_price <= 0.0 or proposal.stop_loss_price <= 0.0:
            return RiskDecisionResult(
                status=RiskCheckResultStatus.REJECTED,
                is_approved=False,
                reason=f"Fail-Safe rejection: Invalid prices (Entry: {proposal.entry_price}, SL: {proposal.stop_loss_price})",
                rule_name="PriceValidation",
                checks=checks,
            )

        risk_per_share = round(abs(proposal.entry_price - proposal.stop_loss_price), 4)
        if risk_per_share <= 0.0:
            return RiskDecisionResult(
                status=RiskCheckResultStatus.REJECTED,
                is_approved=False,
                reason="Fail-Safe rejection: Stop distance is zero or negative",
                rule_name="StopDistanceValidation",
                checks=checks,
            )

        if context.equity <= 0.0 or context.available_cash <= 0.0:
            return RiskDecisionResult(
                status=RiskCheckResultStatus.REJECTED,
                is_approved=False,
                reason=f"Fail-Safe rejection: Invalid account equity ({context.equity}) or available cash ({context.available_cash})",
                rule_name="AccountValidation",
                checks=checks,
            )

        checks["inputs_valid"] = True

        # --- STAGE 2: Daily Loss & Circuit Breaker ---
        loss_ok, loss_reason = self.daily_loss_checker.check(context)
        if not loss_ok:
            return RiskDecisionResult(
                status=RiskCheckResultStatus.REJECTED,
                is_approved=False,
                reason=loss_reason or "Daily loss limit breached",
                rule_name="DailyLossChecker",
                checks=checks,
            )
        checks["daily_loss_valid"] = True

        # --- STAGE 3: Trade & Position Limits ---
        limit_ok, limit_reason = self.trade_limit_checker.check(proposal, context)
        if not limit_ok:
            return RiskDecisionResult(
                status=RiskCheckResultStatus.REJECTED,
                is_approved=False,
                reason=limit_reason or "Trade or position limit exceeded",
                rule_name="TradeLimitChecker",
                checks=checks,
            )
        checks["trade_limits_valid"] = True

        # --- STAGE 4: Deterministic Position Sizing ---
        approved_qty = self.position_sizer.calculate_quantity(proposal, context)
        if approved_qty <= 0:
            return RiskDecisionResult(
                status=RiskCheckResultStatus.REJECTED,
                is_approved=False,
                reason="Calculated position quantity is zero; trade cannot be approved",
                rule_name="PositionSizer",
                checks=checks,
            )
        checks["sizing_valid"] = True

        # --- STAGE 5: Capital & Trade Risk Exposure ---
        cap_ok, cap_reason = self.capital_exposure_checker.check(proposal, approved_qty, context)
        if not cap_ok:
            return RiskDecisionResult(
                status=RiskCheckResultStatus.REJECTED,
                is_approved=False,
                reason=cap_reason or "Capital exposure limit breached",
                rule_name="CapitalExposureChecker",
                approved_quantity=0,
                checks=checks,
            )
        checks["capital_exposure_valid"] = True

        # --- STAGE 6: Sector Exposure ---
        sector_ok, sector_reason = self.sector_exposure_checker.check(proposal, approved_qty, context)
        if not sector_ok:
            return RiskDecisionResult(
                status=RiskCheckResultStatus.REJECTED,
                is_approved=False,
                reason=sector_reason or "Sector concentration limit breached",
                rule_name="SectorExposureChecker",
                approved_quantity=0,
                checks=checks,
            )
        checks["sector_exposure_valid"] = True

        # --- STAGE 7: Approval & Final Metrics ---
        notional_value = round(proposal.entry_price * approved_qty, 2)
        total_risk = round(risk_per_share * approved_qty, 2)
        risk_pct = round(total_risk / context.equity, 4)
        capital_pct = round(notional_value / context.equity, 4)

        return RiskDecisionResult(
            status=RiskCheckResultStatus.APPROVED,
            is_approved=True,
            reason="All risk checks passed successfully",
            rule_name="RiskDecisionEngine",
            approved_quantity=approved_qty,
            risk_per_share=risk_per_share,
            total_risk_amount=total_risk,
            notional_value=notional_value,
            risk_percentage=risk_pct,
            capital_percentage=capital_pct,
            checks=checks,
        )
