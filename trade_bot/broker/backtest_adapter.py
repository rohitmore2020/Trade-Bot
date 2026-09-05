"""
Backtest Broker Adapter.

Simulates broker order execution, realistic fill prices, slippage, and NSE statutory taxes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
import uuid
from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.config.settings import BrokerConfig
from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType
from trade_bot.domain.models import (
    AccountBalance,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    Trade,
)


class BacktestBrokerAdapter(IBrokerAdapter):
    """
    In-memory simulated broker for backtesting and fast deterministic simulations.
    """

    def __init__(self, config: Optional[BrokerConfig] = None) -> None:
        self.config = config or BrokerConfig()
        self._connected: bool = True
        self._orders: Dict[str, Order] = {}
        self._trade_callbacks: List[Callable[[Trade], None]] = []
        self._last_market_prices: Dict[str, float] = {}

    @property
    def name(self) -> str:
        return "BacktestBrokerAdapter"

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def set_market_price(self, symbol: str, price: float) -> None:
        """Update reference market price for fill simulation."""
        self._last_market_prices[symbol] = price

    def register_trade_callback(self, callback: Callable[[Trade], None]) -> None:
        self._trade_callbacks.append(callback)

    def calculate_taxes_and_brokerage(self, turnover: float) -> tuple[float, float]:
        """
        Calculate statutory NSE taxes and brokerage.
        Returns: (brokerage, stt_and_taxes)
        """
        comm = self.config.commission_model
        brokerage = comm.brokerage_per_order
        stt = turnover * comm.stt_percentage
        txn = turnover * comm.transaction_charges_percentage
        gst = (brokerage + txn) * comm.gst_percentage
        sebi = turnover * comm.sebi_charges_percentage
        stamp = turnover * comm.stamp_duty_percentage
        taxes = round(stt + txn + gst + sebi + stamp, 2)
        return round(brokerage, 2), taxes

    def place_order(self, request: OrderRequest) -> str:
        """Simulate order placement and immediate execution if market order."""
        broker_order_id = f"BK_{uuid.uuid4().hex[:10]}"

        # Determine fill price
        base_price = request.price or self._last_market_prices.get(request.symbol, 100.0)
        slippage_pct = self.config.slippage_model.percentage

        # Apply slippage adverse to order side
        if request.side == OrderSide.BUY:
            fill_price = round(base_price * (1.0 + slippage_pct), 2)
        else:
            fill_price = round(base_price * (1.0 - slippage_pct), 2)

        turnover = fill_price * request.quantity
        brokerage, taxes = self.calculate_taxes_and_brokerage(turnover)

        trade = Trade(
            trade_id=f"TRD_{uuid.uuid4().hex[:10]}",
            order_id=broker_order_id,
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            price=fill_price,
            timestamp=datetime.now(timezone.utc),
            brokerage=brokerage,
            stt_and_taxes=taxes,
        )

        # Notify registered execution callbacks
        for cb in self._trade_callbacks:
            cb(trade)

        return broker_order_id

    def modify_order(self, modification: OrderModification) -> bool:
        return True

    def cancel_order(self, broker_order_id: str) -> bool:
        return True

    def get_account_balance(self) -> AccountBalance:
        return AccountBalance(
            initial_capital=100000.0,
            available_cash=100000.0,
            used_margin=0.0,
        )

    def get_positions(self) -> List[Position]:
        return []

    def get_orders(self) -> List[Order]:
        return list(self._orders.values())
