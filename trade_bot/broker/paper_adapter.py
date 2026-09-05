"""
Paper Trading Broker Adapter.

Simulates order execution against real-time market data feed without risking real capital.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, List, Optional
import uuid
from trade_bot.broker.backtest_adapter import BacktestBrokerAdapter
from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.config.settings import BrokerConfig
from trade_bot.domain.enums import OrderStatus, OrderType
from trade_bot.domain.models import (
    AccountBalance,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    Tick,
    Trade,
)


class PaperBrokerAdapter(IBrokerAdapter):
    """
    Paper broker that validates against live market data while recording paper fills.
    Inherits realistic slippage and fee models from backtest simulator.
    """

    def __init__(self, config: Optional[BrokerConfig] = None) -> None:
        self.simulator = BacktestBrokerAdapter(config=config)
        self._trade_callbacks: List[Callable[[Trade], None]] = []

    @property
    def name(self) -> str:
        return "PaperBrokerAdapter"

    def connect(self) -> None:
        self.simulator.connect()

    def disconnect(self) -> None:
        self.simulator.disconnect()

    def is_connected(self) -> bool:
        return self.simulator.is_connected()

    def on_tick(self, tick: Tick) -> None:
        """Update current reference price from live feed."""
        self.simulator.set_market_price(tick.symbol, tick.last_price)

    def register_trade_callback(self, callback: Callable[[Trade], None]) -> None:
        self._trade_callbacks.append(callback)
        self.simulator.register_trade_callback(callback)

    def place_order(self, request: OrderRequest) -> str:
        return self.simulator.place_order(request)

    def modify_order(self, modification: OrderModification) -> bool:
        return self.simulator.modify_order(modification)

    def cancel_order(self, broker_order_id: str) -> bool:
        return self.simulator.cancel_order(broker_order_id)

    def get_account_balance(self) -> AccountBalance:
        return self.simulator.get_account_balance()

    def get_positions(self) -> List[Position]:
        return self.simulator.get_positions()

    def get_orders(self) -> List[Order]:
        return self.simulator.get_orders()
