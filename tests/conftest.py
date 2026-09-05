"""
Shared Test Fixtures for Trade-Bot Test Suite.
"""

from datetime import datetime, timezone
import pytest
from trade_bot.broker.backtest_adapter import BacktestBrokerAdapter
from trade_bot.config.settings import AppConfig, ExecutionMode, RiskConfig
from trade_bot.domain.enums import InstrumentType, OrderSide, OrderType, ProductType
from trade_bot.domain.models import AccountBalance, Instrument, OrderRequest, Tick
from trade_bot.portfolio.manager import PortfolioManager
from trade_bot.risk.manager import RiskManager


@pytest.fixture
def sample_instrument() -> Instrument:
    return Instrument(
        symbol="RELIANCE",
        exchange="NSE",
        segment="EQ",
        instrument_type=InstrumentType.EQUITY,
        lot_size=1,
        tick_size=0.05,
    )


@pytest.fixture
def sample_tick() -> Tick:
    return Tick(
        symbol="RELIANCE",
        timestamp=datetime(2026, 9, 5, 9, 30, 0, tzinfo=timezone.utc),
        last_price=2500.0,
        volume=100,
        total_volume=50000,
    )


@pytest.fixture
def sample_order_request() -> OrderRequest:
    return OrderRequest(
        client_order_id="ORD_TEST_001",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=2500.0,
        stop_loss=2480.0,
        product_type=ProductType.MIS,
    )


@pytest.fixture
def risk_config() -> RiskConfig:
    return RiskConfig(
        initial_capital=100000.0,
        max_daily_loss=5000.0,
        max_loss_per_trade=1500.0,
        max_position_size_per_trade=100000.0,
        max_open_positions=3,
        max_daily_trades=10,
        risk_per_trade_percentage=0.01,
        circuit_breaker_enabled=True,
    )


@pytest.fixture
def risk_manager(risk_config: RiskConfig) -> RiskManager:
    return RiskManager(config=risk_config)


@pytest.fixture
def portfolio_manager() -> PortfolioManager:
    return PortfolioManager(initial_capital=100000.0)


@pytest.fixture
def backtest_broker() -> BacktestBrokerAdapter:
    broker = BacktestBrokerAdapter()
    broker.set_market_price("RELIANCE", 2500.0)
    return broker
