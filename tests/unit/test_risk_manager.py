"""
Unit tests for Risk Management and Pre-trade Validation.
"""

from trade_bot.config.settings import RiskConfig
from trade_bot.domain.enums import OrderSide, OrderType, RiskCheckResultStatus
from trade_bot.domain.models import AccountBalance, OrderRequest, Position
from trade_bot.risk.manager import RiskManager


def test_order_approved_when_within_risk_limits(
    risk_manager: RiskManager,
    sample_order_request: OrderRequest,
) -> None:
    balance = AccountBalance(initial_capital=100000.0, available_cash=100000.0, used_margin=0.0)
    decision = risk_manager.validate_order(sample_order_request, balance, {})
    assert decision.is_approved is True


def test_order_rejected_when_daily_loss_exceeded(
    risk_manager: RiskManager,
    sample_order_request: OrderRequest,
) -> None:
    # Cumulative loss of -6000 breaches max_daily_loss of 5000
    breached_balance = AccountBalance(
        initial_capital=100000.0,
        available_cash=94000.0,
        used_margin=0.0,
        total_realized_pnl=-6000.0,
    )
    decision = risk_manager.validate_order(sample_order_request, breached_balance, {})
    assert decision.is_approved is False
    assert decision.rule_name in ("CircuitBreaker", "MaxDailyLossRule")


def test_order_rejected_when_trade_risk_exceeds_limit(risk_manager: RiskManager) -> None:
    # Price 2500, Stop Loss 2300 = 200 risk/share * 10 = 2000 (exceeds max_loss_per_trade of 1500)
    high_risk_order = OrderRequest(
        client_order_id="HIGH_RISK_01",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=2500.0,
        stop_loss=2300.0,
    )
    balance = AccountBalance(initial_capital=100000.0, available_cash=100000.0, used_margin=0.0)
    decision = risk_manager.validate_order(high_risk_order, balance, {})
    assert decision.is_approved is False
    assert decision.rule_name == "MaxLossPerTradeRule"


def test_calculate_position_size_deterministic(risk_manager: RiskManager) -> None:
    balance = AccountBalance(initial_capital=100000.0, available_cash=100000.0, used_margin=0.0)
    # Entry: 2500, SL: 2450 (Risk = 50/share). 1% of 100k = 1000 max risk.
    # Qty = 1000 / 50 = 20 shares.
    qty = risk_manager.calculate_position_size(
        entry_price=2500.0,
        stop_loss_price=2450.0,
        account_balance=balance,
    )
    assert qty == 20
