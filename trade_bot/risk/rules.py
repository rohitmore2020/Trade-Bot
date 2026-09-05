"""
Concrete Risk Rules.

Enforces financial safety limits and prevents catastrophic drawdowns.
"""

from __future__ import annotations

from typing import Dict
from trade_bot.domain.enums import RiskCheckResultStatus
from trade_bot.domain.models import AccountBalance, OrderRequest, Position, RiskDecision
from trade_bot.risk.interfaces import IRiskRule


class MaxDailyLossRule(IRiskRule):
    """Rejects orders if daily realized + unrealized loss breaches limit."""

    def __init__(self, max_daily_loss: float) -> None:
        self.max_daily_loss = max_daily_loss

    @property
    def rule_name(self) -> str:
        return "MaxDailyLossRule"

    def evaluate(
        self,
        order_request: OrderRequest,
        account_balance: AccountBalance,
        current_positions: Dict[str, Position],
    ) -> RiskDecision:
        current_total_pnl = account_balance.total_realized_pnl + account_balance.total_unrealized_pnl
        if current_total_pnl <= -self.max_daily_loss:
            return RiskDecision(
                status=RiskCheckResultStatus.REJECTED,
                reason=f"Daily loss limit breached: Current PnL {current_total_pnl:.2f} <= Limit -{self.max_daily_loss:.2f}",
                rule_name=self.rule_name,
                order_request=order_request,
            )
        return RiskDecision(
            status=RiskCheckResultStatus.APPROVED,
            reason="Daily loss within allowable limits",
            rule_name=self.rule_name,
            order_request=order_request,
        )


class MaxLossPerTradeRule(IRiskRule):
    """Rejects orders where potential loss at stop-loss exceeds limit."""

    def __init__(self, max_loss_per_trade: float) -> None:
        self.max_loss_per_trade = max_loss_per_trade

    @property
    def rule_name(self) -> str:
        return "MaxLossPerTradeRule"

    def evaluate(
        self,
        order_request: OrderRequest,
        account_balance: AccountBalance,
        current_positions: Dict[str, Position],
    ) -> RiskDecision:
        if order_request.stop_loss is not None and order_request.price is not None:
            risk_per_share = abs(order_request.price - order_request.stop_loss)
            total_risk = risk_per_share * order_request.quantity
            if total_risk > self.max_loss_per_trade:
                return RiskDecision(
                    status=RiskCheckResultStatus.REJECTED,
                    reason=f"Trade risk {total_risk:.2f} exceeds max allowed per trade {self.max_loss_per_trade:.2f}",
                    rule_name=self.rule_name,
                    order_request=order_request,
                )
        return RiskDecision(
            status=RiskCheckResultStatus.APPROVED,
            reason="Trade risk within allowable limit",
            rule_name=self.rule_name,
            order_request=order_request,
        )


class MaxPositionSizeRule(IRiskRule):
    """Rejects orders exceeding max notional position size in a single asset."""

    def __init__(self, max_position_size: float) -> None:
        self.max_position_size = max_position_size

    @property
    def rule_name(self) -> str:
        return "MaxPositionSizeRule"

    def evaluate(
        self,
        order_request: OrderRequest,
        account_balance: AccountBalance,
        current_positions: Dict[str, Position],
    ) -> RiskDecision:
        order_price = order_request.price or 0.0
        notional_value = order_price * order_request.quantity
        if notional_value > self.max_position_size:
            return RiskDecision(
                status=RiskCheckResultStatus.REJECTED,
                reason=f"Notional value {notional_value:.2f} exceeds max position size {self.max_position_size:.2f}",
                rule_name=self.rule_name,
                order_request=order_request,
            )
        return RiskDecision(
            status=RiskCheckResultStatus.APPROVED,
            reason="Position size within allowable limits",
            rule_name=self.rule_name,
            order_request=order_request,
        )


class MaxOpenPositionsRule(IRiskRule):
    """Rejects new position opening if max concurrent open positions is reached."""

    def __init__(self, max_open_positions: int) -> None:
        self.max_open_positions = max_open_positions

    @property
    def rule_name(self) -> str:
        return "MaxOpenPositionsRule"

    def evaluate(
        self,
        order_request: OrderRequest,
        account_balance: AccountBalance,
        current_positions: Dict[str, Position],
    ) -> RiskDecision:
        existing_pos = current_positions.get(order_request.symbol)
        is_new_symbol = existing_pos is None or existing_pos.is_flat
        open_positions_count = sum(1 for p in current_positions.values() if not p.is_flat)

        if is_new_symbol and open_positions_count >= self.max_open_positions:
            return RiskDecision(
                status=RiskCheckResultStatus.REJECTED,
                reason=f"Open positions count ({open_positions_count}) reached maximum limit of {self.max_open_positions}",
                rule_name=self.rule_name,
                order_request=order_request,
            )
        return RiskDecision(
            status=RiskCheckResultStatus.APPROVED,
            reason="Open position count within allowable limit",
            rule_name=self.rule_name,
            order_request=order_request,
        )


class AvailableCashRule(IRiskRule):
    """Rejects orders requiring margin greater than available cash."""

    def __init__(self, buffer_percentage: float = 0.05) -> None:
        self.buffer_percentage = buffer_percentage

    @property
    def rule_name(self) -> str:
        return "AvailableCashRule"

    def evaluate(
        self,
        order_request: OrderRequest,
        account_balance: AccountBalance,
        current_positions: Dict[str, Position],
    ) -> RiskDecision:
        order_price = order_request.price or 0.0
        required_capital = (order_price * order_request.quantity) * (1.0 + self.buffer_percentage)
        if required_capital > account_balance.available_cash:
            return RiskDecision(
                status=RiskCheckResultStatus.REJECTED,
                reason=f"Required capital {required_capital:.2f} exceeds available cash {account_balance.available_cash:.2f}",
                rule_name=self.rule_name,
                order_request=order_request,
            )
        return RiskDecision(
            status=RiskCheckResultStatus.APPROVED,
            reason="Available cash sufficient for order",
            rule_name=self.rule_name,
            order_request=order_request,
        )
