"""
Deterministic Unit Tests for Independent Risk Management Engine (Phase 9).

Covers:
1. Valid trade approval and position sizing
2. Risk exceeds 0.5% limit handling and rejection
3. Capital exceeds 20% equity cap capping and rejection
4. Daily loss 2.0% limit reached (circuit breaker)
5. Maximum simultaneous positions (3) reached
6. Maximum trades per day (6) reached
7. Sector concentration (40%) exceeded
8. Zero and negative stop distance rejection
9. Invalid equity rejection
10. Invalid price rejection
11. Quantity rounding and lot-size constraints
12. Regime-based size reduction (VIX elevated/extreme, market neutral)
13. Multiple simultaneous positions accounting
14. Conservative fail-safe rejection on missing information
15. Zero calculated quantity never approved
16. Exact boundary conditions
"""

from datetime import datetime, timezone
import pytest

from trade_bot.domain.enums import MarketRegime, OrderSide, ProductType, RiskCheckResultStatus
from trade_bot.domain.models import Instrument, Position
from trade_bot.indicators.vix_filter import VIXRegime
from trade_bot.risk.capital_exposure_checker import CapitalExposureChecker
from trade_bot.risk.daily_loss_checker import DailyLossChecker
from trade_bot.risk.decision_engine import RiskDecisionEngine
from trade_bot.risk.models import (
    RiskAssessmentContext,
    RiskParameters,
    TradeProposal,
)
from trade_bot.risk.position_sizer import PositionSizer
from trade_bot.risk.sector_exposure_checker import SectorExposureChecker
from trade_bot.risk.trade_limit_checker import TradeLimitChecker
from trade_bot.strategy.models import TradeIntent


@pytest.fixture
def risk_engine() -> RiskDecisionEngine:
    return RiskDecisionEngine()


@pytest.fixture
def standard_context() -> RiskAssessmentContext:
    return RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=1_000_000.0,
        daily_realized_pnl=0.0,
        daily_unrealized_pnl=0.0,
        daily_executed_trades=0,
        current_positions={},
        symbol_sector_map={
            "RELIANCE": "ENERGY",
            "TCS": "IT",
            "INFY": "IT",
            "HDFCBANK": "BANKING",
            "ICICIBANK": "BANKING",
            "TATAMOTORS": "AUTO",
        },
        market_regime=MarketRegime.BULLISH,
        vix_regime=VIXRegime.NORMAL,
    )


# ==============================================================================
# 1. Valid Trade Approval
# ==============================================================================

def test_valid_trade_approval(risk_engine: RiskDecisionEngine, standard_context: RiskAssessmentContext) -> None:
    # Equity: 1,000,000. 0.5% risk budget = 5,000.
    # Entry: 1,000, SL: 950 -> risk/share = 50.
    # Sized quantity = 5,000 / 50 = 100 shares.
    # Notional value = 100 * 1,000 = 100,000 (10% of equity, <= 20% cap = 200,000).
    proposal = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=950.0,
        sector="ENERGY",
    )

    decision = risk_engine.evaluate(proposal, standard_context)
    assert decision.is_approved is True
    assert decision.status == RiskCheckResultStatus.APPROVED
    assert decision.approved_quantity == 100
    assert decision.total_risk_amount == 5000.0
    assert decision.notional_value == 100000.0
    assert decision.risk_percentage == 0.005  # 0.5%
    assert decision.capital_percentage == 0.10  # 10%


# ==============================================================================
# 2. Risk Exceeds 0.5% Handling
# ==============================================================================

def test_risk_exceeds_half_percent(standard_context: RiskAssessmentContext) -> None:
    checker = CapitalExposureChecker()
    proposal = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=950.0,
        sector="ENERGY",
    )
    # Equity = 1,000,000 -> max 0.5% risk = 5,000
    # Qty 101 -> Risk = 101 * 50 = 5,050 (> 5,000 max allowed)
    is_ok, reason = checker.check(proposal, quantity=101, context=standard_context)
    assert is_ok is False
    assert "exceeds maximum allowed" in str(reason)


# ==============================================================================
# 3. Capital Exceeds 20% Cap Handling
# ==============================================================================

def test_capital_exceeds_twenty_percent(risk_engine: RiskDecisionEngine, standard_context: RiskAssessmentContext) -> None:
    # Equity: 1,000,000. 20% capital cap = 200,000.
    # Entry: 1,000, SL: 998 -> Risk/share = 2.0.
    # Raw risk quantity = 5,000 / 2 = 2,500 shares (notional 2,500,000 = 250% of equity!).
    # Sizer must cap at 20% capital: 200,000 / 1,000 = 200 shares.
    proposal = TradeProposal(
        symbol="TCS",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=998.0,
        sector="IT",
    )

    decision = risk_engine.evaluate(proposal, standard_context)
    assert decision.is_approved is True
    assert decision.approved_quantity == 200
    assert decision.notional_value == 200000.0
    assert decision.capital_percentage == 0.20

    # Direct check: quantity 201 (notional 201,000 > 200,000) must be rejected
    checker = CapitalExposureChecker()
    is_ok, reason = checker.check(proposal, quantity=201, context=standard_context)
    assert is_ok is False
    assert "Capital per trade" in str(reason)


# ==============================================================================
# 4. Daily Loss Limit (2.0% Circuit Breaker)
# ==============================================================================

def test_daily_loss_limit_reached(risk_engine: RiskDecisionEngine, standard_context: RiskAssessmentContext) -> None:
    proposal = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=950.0,
        sector="ENERGY",
    )

    # 1. Below 2% loss (-19,999 on 1,000,000) -> Allowed
    context_below = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=980_001.0,
        daily_realized_pnl=-19999.0,
        current_positions={},
    )
    decision_below = risk_engine.evaluate(proposal, context_below)
    assert decision_below.is_approved is True

    # 2. Exactly at 2% loss (-20,000 on 1,000,000) -> Rejection boundary
    context_exact = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=980_000.0,
        daily_realized_pnl=-20000.0,
        current_positions={},
    )
    decision_exact = risk_engine.evaluate(proposal, context_exact)
    assert decision_exact.is_approved is False
    assert "Daily loss limit breached" in decision_exact.reason

    # 3. Beyond 2% loss (-25,000 on 1,000,000) -> Rejected
    context_breached = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=975_000.0,
        daily_realized_pnl=-25000.0,
        current_positions={},
    )
    decision_breached = risk_engine.evaluate(proposal, context_breached)
    assert decision_breached.is_approved is False
    assert decision_breached.rule_name == "DailyLossChecker"


# ==============================================================================
# 5. Maximum Simultaneous Positions (3)
# ==============================================================================

def test_maximum_positions_reached(risk_engine: RiskDecisionEngine, standard_context: RiskAssessmentContext) -> None:
    proposal = TradeProposal(
        symbol="TATAMOTORS",
        side=OrderSide.BUY,
        entry_price=800.0,
        stop_loss_price=760.0,
        sector="AUTO",
    )

    # Context with 2 open positions -> Allowed
    pos1 = Position(symbol="RELIANCE", quantity=50, average_price=2500.0, last_price=2520.0)
    pos2 = Position(symbol="TCS", quantity=40, average_price=3500.0, last_price=3510.0)
    context_2_pos = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=700_000.0,
        current_positions={"RELIANCE": pos1, "TCS": pos2},
    )
    assert risk_engine.evaluate(proposal, context_2_pos).is_approved is True

    # Context with 3 open positions -> Rejected for new symbol
    pos3 = Position(symbol="HDFCBANK", quantity=100, average_price=1600.0, last_price=1610.0)
    context_3_pos = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=500_000.0,
        current_positions={"RELIANCE": pos1, "TCS": pos2, "HDFCBANK": pos3},
    )
    decision = risk_engine.evaluate(proposal, context_3_pos)
    assert decision.is_approved is False
    assert "Maximum simultaneous positions limit reached: 3 >= 3" in decision.reason

    # If position already exists for that symbol -> Allowed
    proposal_existing = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=2500.0,
        stop_loss_price=2450.0,
        sector="ENERGY",
    )
    assert risk_engine.evaluate(proposal_existing, context_3_pos).is_approved is True


# ==============================================================================
# 6. Maximum Daily Trades (6)
# ==============================================================================

def test_maximum_trades_reached(risk_engine: RiskDecisionEngine) -> None:
    proposal = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=950.0,
        sector="ENERGY",
    )

    # 5 trades -> Allowed
    context_5 = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=1_000_000.0,
        daily_executed_trades=5,
    )
    assert risk_engine.evaluate(proposal, context_5).is_approved is True

    # 6 trades -> Rejected (boundary)
    context_6 = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=1_000_000.0,
        daily_executed_trades=6,
    )
    decision = risk_engine.evaluate(proposal, context_6)
    assert decision.is_approved is False
    assert "Maximum daily trades limit reached: 6 >= 6" in decision.reason


# ==============================================================================
# 7. Sector Concentration Limit (40%)
# ==============================================================================

def test_sector_exposure_exceeded(risk_engine: RiskDecisionEngine) -> None:
    # Equity: 1,000,000. Max 40% sector limit = 400,000.
    # Existing HDFCBANK (BANKING) = 150 shares * 1,600 = 240,000 notional.
    pos_hdfc = Position(symbol="HDFCBANK", quantity=150, average_price=1600.0, last_price=1600.0)
    context = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=700_000.0,
        current_positions={"HDFCBANK": pos_hdfc},
        symbol_sector_map={"HDFCBANK": "BANKING", "ICICIBANK": "BANKING"},
    )

    # Proposed ICICIBANK trade (price 1,000, SL 950 -> risk 50)
    # Sizer would normally give 100 shares (100,000 notional).
    # 240,000 + 100,000 = 340,000 <= 400,000 (34%) -> Approved
    proposal_normal = TradeProposal(
        symbol="ICICIBANK",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=950.0,
        sector="BANKING",
    )
    assert risk_engine.evaluate(proposal_normal, context).is_approved is True

    # Direct Sector Checker Test on Boundary:
    sector_checker = SectorExposureChecker()

    # Case A: 160 shares * 1,000 = 160,000. Total = 240k + 160k = 400,000 (Exact 40.0% boundary -> passes)
    is_ok_exact, _ = sector_checker.check(proposal_normal, quantity=160, context=context)
    assert is_ok_exact is True

    # Case B: 161 shares * 1,000 = 161,000. Total = 240k + 161k = 401,000 (> 400,000 -> fails)
    is_ok_breach, breach_reason = sector_checker.check(proposal_normal, quantity=161, context=context)
    assert is_ok_breach is False
    assert "Sector exposure for 'BANKING'" in str(breach_reason)


# ==============================================================================
# 8. Zero and Negative Stop Distance
# ==============================================================================

def test_zero_or_negative_stop_distance(risk_engine: RiskDecisionEngine, standard_context: RiskAssessmentContext) -> None:
    # Zero stop distance
    proposal_zero = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=1000.0,
        sector="ENERGY",
    )
    dec_zero = risk_engine.evaluate(proposal_zero, standard_context)
    assert dec_zero.is_approved is False
    assert "Stop distance is zero or negative" in dec_zero.reason

    # Negative stop price
    proposal_neg = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=-50.0,
        sector="ENERGY",
    )
    dec_neg = risk_engine.evaluate(proposal_neg, standard_context)
    assert dec_neg.is_approved is False
    assert "Invalid prices" in dec_neg.reason


# ==============================================================================
# 9. Invalid Equity
# ==============================================================================

def test_invalid_equity(risk_engine: RiskDecisionEngine) -> None:
    proposal = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=950.0,
        sector="ENERGY",
    )

    context_zero_eq = RiskAssessmentContext(equity=0.0, available_cash=100000.0)
    assert risk_engine.evaluate(proposal, context_zero_eq).is_approved is False

    context_neg_eq = RiskAssessmentContext(equity=-50000.0, available_cash=100000.0)
    assert risk_engine.evaluate(proposal, context_neg_eq).is_approved is False


# ==============================================================================
# 10. Invalid Price
# ==============================================================================

def test_invalid_price(risk_engine: RiskDecisionEngine, standard_context: RiskAssessmentContext) -> None:
    proposal_zero_price = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=0.0,
        stop_loss_price=950.0,
        sector="ENERGY",
    )
    assert risk_engine.evaluate(proposal_zero_price, standard_context).is_approved is False

    proposal_neg_price = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=-1000.0,
        stop_loss_price=950.0,
        sector="ENERGY",
    )
    assert risk_engine.evaluate(proposal_neg_price, standard_context).is_approved is False


# ==============================================================================
# 11. Quantity Rounding and Lot Size
# ==============================================================================

def test_quantity_rounding_and_lot_size() -> None:
    sizer = PositionSizer()
    context = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=1_000_000.0,
    )
    # Risk budget = 5,000. Entry: 1000, SL: 943.18 -> Risk/share = 56.82.
    # Raw qty = 5000 / 56.82 = 88.00 -> 88 shares.
    # Lot size = 25 -> (88 // 25) * 25 = 75 shares.
    proposal = TradeProposal(
        symbol="NIFTY",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=943.18,
        lot_size=25,
    )
    qty = sizer.calculate_quantity(proposal, context)
    assert qty == 75

    # If raw qty < lot size (e.g. raw qty = 20, lot size = 25) -> returns 0
    proposal_large_lot = TradeProposal(
        symbol="NIFTY",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=700.0,  # risk 300 -> raw qty 5000/300 = 16
        lot_size=25,
    )
    assert sizer.calculate_quantity(proposal_large_lot, context) == 0


# ==============================================================================
# 12. Regime-Based Size Reduction
# ==============================================================================

def test_regime_based_size_reduction() -> None:
    sizer = PositionSizer()
    # Baseline: Normal VIX -> 100 shares
    proposal = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=950.0,
    )
    context_normal = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=1_000_000.0,
        vix_regime=VIXRegime.NORMAL,
        market_regime=MarketRegime.BULLISH,
    )
    assert sizer.calculate_quantity(proposal, context_normal) == 100

    # Elevated VIX (24–28) -> 50% size reduction -> 50 shares
    context_elevated = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=1_000_000.0,
        vix_regime=VIXRegime.ELEVATED,
        market_regime=MarketRegime.BULLISH,
    )
    assert sizer.calculate_quantity(proposal, context_elevated) == 50

    # Extreme VIX (>28) -> 0 shares (trading halted)
    context_extreme = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=1_000_000.0,
        vix_regime=VIXRegime.EXTREME,
        market_regime=MarketRegime.BULLISH,
    )
    assert sizer.calculate_quantity(proposal, context_extreme) == 0

    # Neutral Market Regime -> 0 shares
    context_neutral = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=1_000_000.0,
        vix_regime=VIXRegime.NORMAL,
        market_regime=MarketRegime.NEUTRAL,
    )
    assert sizer.calculate_quantity(proposal, context_neutral) == 0


# ==============================================================================
# 13. Multiple Simultaneous Positions Accounting
# ==============================================================================

def test_multiple_simultaneous_positions_accounting(risk_engine: RiskDecisionEngine) -> None:
    # 2 positions already open in different sectors
    pos1 = Position(symbol="RELIANCE", quantity=80, average_price=2500.0, last_price=2500.0)  # 200k in ENERGY
    pos2 = Position(symbol="TCS", quantity=50, average_price=3500.0, last_price=3500.0)       # 175k in IT
    context = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=625_000.0,
        current_positions={"RELIANCE": pos1, "TCS": pos2},
        symbol_sector_map={"RELIANCE": "ENERGY", "TCS": "IT", "HDFCBANK": "BANKING"},
    )

    # 3rd position in BANKING
    proposal_3 = TradeProposal(
        symbol="HDFCBANK",
        side=OrderSide.BUY,
        entry_price=1600.0,
        stop_loss_price=1550.0,  # risk 50 -> 100 shares = 160,000 notional (16% capital, 16% sector)
        sector="BANKING",
    )
    decision = risk_engine.evaluate(proposal_3, context)
    assert decision.is_approved is True
    assert decision.approved_quantity == 100


# ==============================================================================
# 14. Fail-Safe Missing Information Rejection
# ==============================================================================

def test_fail_safe_missing_information(risk_engine: RiskDecisionEngine) -> None:
    # Missing sector information must be rejected per conservative fail-safe policy
    proposal_no_sector = TradeProposal(
        symbol="UNKNOWN_STOCK",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=950.0,
        sector=None,
    )
    context_no_sector = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=1_000_000.0,
        symbol_sector_map={},
    )
    decision = risk_engine.evaluate(proposal_no_sector, context_no_sector)
    assert decision.is_approved is False
    assert "Missing sector classification" in decision.reason


# ==============================================================================
# 15. Zero Calculated Quantity Never Approved
# ==============================================================================

def test_zero_quantity_never_approved(risk_engine: RiskDecisionEngine) -> None:
    # Available cash is ₹500, but stock costs ₹1000 -> Quantity 0
    proposal = TradeProposal(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        entry_price=1000.0,
        stop_loss_price=950.0,
        sector="ENERGY",
    )
    context_low_cash = RiskAssessmentContext(
        equity=1_000_000.0,
        available_cash=500.0,
    )
    decision = risk_engine.evaluate(proposal, context_low_cash)
    assert decision.is_approved is False
    assert "Calculated position quantity is zero" in decision.reason


# ==============================================================================
# 16. Evaluate from Phase 8 TradeIntent Adapter
# ==============================================================================

def test_evaluate_from_trade_intent(risk_engine: RiskDecisionEngine, standard_context: RiskAssessmentContext) -> None:
    intent = TradeIntent(
        strategy_version="1.0.0",
        timestamp=datetime.now(timezone.utc),
        instrument=Instrument("RELIANCE"),
        side=OrderSide.BUY,
        signal_price=1000.0,
        proposed_entry_price=1000.0,
        proposed_stop_price=950.0,
        atr=25.0,
        vwap=990.0,
        or_high=995.0,
        or_low=970.0,
        volume_ratio=2.0,
        signal_reason="LONG_ENTRY",
    )

    decision = risk_engine.evaluate_from_intent(intent, standard_context, sector="ENERGY")
    assert decision.is_approved is True
    assert decision.approved_quantity == 100
    assert decision.notional_value == 100000.0
