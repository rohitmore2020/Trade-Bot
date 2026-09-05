"""
Risk Manager.

Coordinates pre-trade validation, circuit breakers, and capital allocation.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from trade_bot.config.settings import RiskConfig
from trade_bot.domain.enums import RiskCheckResultStatus
from trade_bot.domain.models import AccountBalance, OrderRequest, Position, RiskDecision
from trade_bot.risk.interfaces import IRiskManager, IRiskRule
from trade_bot.risk.rules import (
    AvailableCashRule,
    MaxDailyLossRule,
    MaxLossPerTradeRule,
    MaxOpenPositionsRule,
    MaxPositionSizeRule,
)


class RiskManager(IRiskManager):
    """
    Evaluates order requests against pre-configured risk rules and enforces circuit breaker limits.
    """

    def __init__(self, config: RiskConfig, custom_rules: Optional[List[IRiskRule]] = None) -> None:
        self.config = config
        self._circuit_breaker_tripped: bool = False
        self._rules: List[IRiskRule] = custom_rules or [
            MaxDailyLossRule(max_daily_loss=config.max_daily_loss),
            MaxLossPerTradeRule(max_loss_per_trade=config.max_loss_per_trade),
            MaxPositionSizeRule(max_position_size=config.max_position_size_per_trade),
            MaxOpenPositionsRule(max_open_positions=config.max_open_positions),
            AvailableCashRule(),
        ]

    def add_rule(self, rule: IRiskRule) -> None:
        """Add an additional risk rule to the validation pipeline."""
        self._rules.append(rule)

    def check_circuit_breaker(self, account_balance: AccountBalance) -> bool:
        """
        Check if total daily loss exceeds max_daily_loss. If tripped, halts trading.
        """
        total_pnl = account_balance.total_realized_pnl + account_balance.total_unrealized_pnl
        if self.config.circuit_breaker_enabled and total_pnl <= -self.config.max_daily_loss:
            self._circuit_breaker_tripped = True
            return True
        return self._circuit_breaker_tripped

    def validate_order(
        self,
        order_request: OrderRequest,
        account_balance: AccountBalance,
        current_positions: Dict[str, Position],
    ) -> RiskDecision:
        """
        Validate an order against all configured risk rules sequentially.
        Fails fast upon first rejection.
        """
        if self.check_circuit_breaker(account_balance):
            return RiskDecision(
                status=RiskCheckResultStatus.REJECTED,
                reason="Trading halted: Circuit breaker is tripped due to max daily loss breach",
                rule_name="CircuitBreaker",
                order_request=order_request,
            )

        for rule in self._rules:
            decision = rule.evaluate(order_request, account_balance, current_positions)
            if not decision.is_approved:
                return decision

        return RiskDecision(
            status=RiskCheckResultStatus.APPROVED,
            reason="All pre-trade risk checks passed successfully",
            rule_name="RiskManager",
            order_request=order_request,
        )

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        account_balance: AccountBalance,
    ) -> int:
        """
        Calculate deterministic position size based on fixed fractional risk:
        Risk Capital = Total Equity * risk_per_trade_percentage
        Quantity = Risk Capital / abs(entry_price - stop_loss_price)
        Clamped by max_position_size_per_trade and available_cash.
        """
        if entry_price <= 0 or stop_loss_price <= 0 or entry_price == stop_loss_price:
            return 0

        risk_per_share = abs(entry_price - stop_loss_price)
        total_equity = account_balance.total_equity
        target_risk_amount = min(
            total_equity * self.config.risk_per_trade_percentage,
            self.config.max_loss_per_trade,
        )

        qty = int(target_risk_amount / risk_per_share)
        if qty <= 0:
            return 0

        # Cap by max position size in notional terms
        max_qty_by_size = int(self.config.max_position_size_per_trade / entry_price)
        qty = min(qty, max_qty_by_size)

        # Cap by available cash
        max_qty_by_cash = int(account_balance.available_cash / entry_price)
        qty = min(qty, max_qty_by_cash)

        return max(0, qty)
