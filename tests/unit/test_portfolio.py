"""
Unit tests for Portfolio Manager.
"""

from datetime import datetime, timezone
from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import Trade
from trade_bot.portfolio.manager import PortfolioManager


def test_portfolio_manager_cash_and_pnl_accounting() -> None:
    pm = PortfolioManager(initial_capital=100000.0)
    bal_initial = pm.get_account_balance()
    assert bal_initial.available_cash == 100000.0

    # Execute BUY fill: 10 shares @ 2000 = 20000 + 25 fees
    buy_trade = Trade(
        trade_id="T_1",
        order_id="O_1",
        client_order_id="C_1",
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=10,
        price=2000.0,
        timestamp=datetime.now(timezone.utc),
        brokerage=20.0,
        stt_and_taxes=5.0,
    )
    pm.process_fill(buy_trade)

    pos = pm.get_position("INFY")
    assert pos is not None
    assert pos.quantity == 10
    assert pos.average_price == 2000.0
    assert pm.available_cash == 100000.0 - 20025.0

    # Market price moves up to 2050
    pm.update_market_price("INFY", 2050.0)
    assert pos.unrealized_pnl == 500.0  # (2050 - 2000) * 10

    # Sell 10 shares @ 2050 to close position
    sell_trade = Trade(
        trade_id="T_2",
        order_id="O_2",
        client_order_id="C_2",
        symbol="INFY",
        side=OrderSide.SELL,
        quantity=10,
        price=2050.0,
        timestamp=datetime.now(timezone.utc),
        brokerage=20.0,
        stt_and_taxes=5.0,
    )
    pm.process_fill(sell_trade)

    assert pos.is_flat is True
    # Realized PnL = 500 - 25 fees = 475
    assert pos.realized_pnl == 475.0
