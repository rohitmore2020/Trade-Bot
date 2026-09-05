"""
Unit tests for Broker Adapters.
"""

from typing import List
import pytest
from trade_bot.broker.backtest_adapter import BacktestBrokerAdapter
from trade_bot.broker.paper_adapter import PaperBrokerAdapter
from trade_bot.broker.upstox_adapter import UpstoxBrokerAdapter
from trade_bot.config.settings import BrokerConfig
from trade_bot.domain.enums import OrderSide, OrderType
from trade_bot.domain.exceptions import BrokerAdapterError
from trade_bot.domain.models import OrderRequest, Trade


def test_backtest_broker_executes_with_slippage(sample_order_request: OrderRequest) -> None:
    broker = BacktestBrokerAdapter()
    broker.set_market_price("RELIANCE", 2500.0)

    trades: List[Trade] = []
    broker.register_trade_callback(trades.append)

    order_id = broker.place_order(sample_order_request)
    assert order_id.startswith("BK_")
    assert len(trades) == 1
    # Buy order price should have positive slippage: 2500 * (1 + 0.0005) = 2501.25
    assert trades[0].price > 2500.0
    assert trades[0].quantity == sample_order_request.quantity


def test_paper_broker_adapter_delegation(sample_order_request: OrderRequest) -> None:
    paper_broker = PaperBrokerAdapter()
    trades: List[Trade] = []
    paper_broker.register_trade_callback(trades.append)

    order_id = paper_broker.place_order(sample_order_request)
    assert order_id.startswith("BK_")
    assert len(trades) == 1


def test_upstox_broker_stub_blocks_live_trading_safely(sample_order_request: OrderRequest) -> None:
    upstox_broker = UpstoxBrokerAdapter(config=BrokerConfig(), allow_live=False)
    assert upstox_broker.is_connected() is False

    # connect without allow_live must raise BrokerAdapterError
    with pytest.raises(BrokerAdapterError, match="blocked"):
        upstox_broker.connect()

    # place_order must raise BrokerAdapterError
    with pytest.raises(BrokerAdapterError, match="Live order placement is strictly blocked"):
        upstox_broker.place_order(sample_order_request)
