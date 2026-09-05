"""
Risk Management Protocols and Interfaces.

Pre-trade risk filters validate every order request prior to routing to execution/broker.
"""

from __future__ import annotations

from typing import Dict, List, Protocol, runtime_checkable
from trade_bot.domain.models import AccountBalance, OrderRequest, Position, RiskDecision


@runtime_checkable
class IRiskRule(Protocol):
    """Protocol for a single pre-trade risk check."""

    @property
    def rule_name(self) -> str:
        """Name of the risk rule."""
        ...

    def evaluate(
        self,
        order_request: OrderRequest,
        account_balance: AccountBalance,
        current_positions: Dict[str, Position],
    ) -> RiskDecision:
        """Evaluate order request against this risk rule."""
        ...


@runtime_checkable
class IRiskManager(Protocol):
    """Protocol for overall portfolio and trade risk governance."""

    def validate_order(
        self,
        order_request: OrderRequest,
        account_balance: AccountBalance,
        current_positions: Dict[str, Position],
    ) -> RiskDecision:
        """Validate order request against all registered risk rules."""
        ...

    def check_circuit_breaker(self, account_balance: AccountBalance) -> bool:
        """Returns True if circuit breaker is triggered (trading must halt)."""
        ...
