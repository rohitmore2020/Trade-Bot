"""
Unit tests for Execution Engine and Idempotency.
"""

import pytest
from trade_bot.broker.backtest_adapter import BacktestBrokerAdapter
from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType
from trade_bot.domain.exceptions import DuplicateOrderError
from trade_bot.domain.models import OrderRequest
from trade_bot.execution.engine import ExecutionEngine
from trade_bot.portfolio.manager import PortfolioManager
from trade_bot.risk.manager import RiskManager


def test_execution_engine_submits_and_tracks_order(
    backtest_broker: BacktestBrokerAdapter,
    risk_manager: RiskManager,
    portfolio_manager: PortfolioManager,
    sample_order_request: OrderRequest,
) -> None:
    engine = ExecutionEngine(
        broker=backtest_broker,
        risk_manager=risk_manager,
        portfolio_manager=portfolio_manager,
    )
    # Wire broker fills
    backtest_broker.register_trade_callback(engine.handle_fill)

    order = engine.submit_order(sample_order_request)
    assert order.client_order_id == sample_order_request.client_order_id
    # Since BacktestBroker immediately executes, order should be FILLED
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == sample_order_request.quantity


def test_execution_engine_rejects_duplicate_order(
    backtest_broker: BacktestBrokerAdapter,
    risk_manager: RiskManager,
    portfolio_manager: PortfolioManager,
    sample_order_request: OrderRequest,
) -> None:
    engine = ExecutionEngine(
        broker=backtest_broker,
        risk_manager=risk_manager,
        portfolio_manager=portfolio_manager,
    )
    # First submit succeeds
    engine.submit_order(sample_order_request)

    # Second submit with same client_order_id must raise DuplicateOrderError
    with pytest.raises(DuplicateOrderError):
        engine.submit_order(sample_order_request)
