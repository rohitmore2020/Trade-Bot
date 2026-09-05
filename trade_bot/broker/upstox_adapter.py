"""
Upstox Broker Adapter Placeholder / Stub.

Strictly guarded placeholder implementing IBrokerAdapter.
Per Phase 0 requirements, live connections and real order placements are disabled.
"""

from __future__ import annotations

from typing import Callable, List, Optional
from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.config.settings import BrokerConfig
from trade_bot.domain.exceptions import BrokerAdapterError
from trade_bot.domain.models import (
    AccountBalance,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    Trade,
)


class UpstoxBrokerAdapter(IBrokerAdapter):
    """
    Adapter skeleton for Upstox API v2.
    Active integration is strictly guarded for future phases.
    """

    def __init__(self, config: BrokerConfig, allow_live: bool = False) -> None:
        self.config = config
        self.allow_live = allow_live
        self._is_connected: bool = False
        self._trade_callbacks: List[Callable[[Trade], None]] = []

    @property
    def name(self) -> str:
        return "UpstoxBrokerAdapter"

    def connect(self) -> None:
        if not self.allow_live:
            raise BrokerAdapterError(
                "Upstox live connection blocked: allow_live_trading is False. "
                "Live trading must be explicitly authorized."
            )
        raise NotImplementedError(
            "Upstox live integration is scheduled for Phase 5. Live connectivity is disabled in Phase 0."
        )

    def disconnect(self) -> None:
        self._is_connected = False

    def is_connected(self) -> bool:
        return self._is_connected

    def get_account_balance(self) -> AccountBalance:
        raise NotImplementedError("Upstox live API not enabled in this phase.")

    def get_positions(self) -> List[Position]:
        raise NotImplementedError("Upstox live API not enabled in this phase.")

    def get_orders(self) -> List[Order]:
        raise NotImplementedError("Upstox live API not enabled in this phase.")

    def place_order(self, request: OrderRequest) -> str:
        raise BrokerAdapterError("Live order placement is strictly blocked in Phase 0.")

    def modify_order(self, modification: OrderModification) -> bool:
        raise BrokerAdapterError("Live order modification is strictly blocked in Phase 0.")

    def cancel_order(self, broker_order_id: str) -> bool:
        raise BrokerAdapterError("Live order cancellation is strictly blocked in Phase 0.")

    def register_trade_callback(self, callback: Callable[[Trade], None]) -> None:
        self._trade_callbacks.append(callback)
