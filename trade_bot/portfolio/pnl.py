"""
P&L Calculation and Transaction Cost Model.

Provides separate calculations for:
- Gross P&L
- Realized P&L
- Unrealized P&L
- Transaction Costs (Brokerage, STT, Exchange Turnover, SEBI, GST)
- Slippage
- Net P&L

Zero external infrastructure dependencies; pure financial arithmetic.
"""

from __future__ import annotations

from typing import Optional

from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import Position


class PnLCalculator:
    """
    Computes distinct P&L components conforming to Indian NSE statutory fee schedule.
    """

    @staticmethod
    def calculate_gross_pnl(
        entry_side: OrderSide,
        entry_price: float,
        exit_price: float,
        quantity: int,
    ) -> float:
        """
        Calculates gross price-spread P&L before any fees or slippage.
        """
        if entry_side == OrderSide.BUY:
            return round((exit_price - entry_price) * quantity, 2)
        else:
            return round((entry_price - exit_price) * quantity, 2)

    @staticmethod
    def calculate_transaction_costs(
        price: float,
        quantity: int,
        side: OrderSide,
    ) -> float:
        """
        Calculates Indian cash equity intraday statutory charges:
        - Brokerage: min(₹20, 0.03% of turnover)
        - STT: 0.025% on sell side turnover
        - NSE transaction charges: 0.00345% of turnover
        - SEBI turnover charges: ₹10 per crore (0.0001% of turnover)
        - GST: 18% on (Brokerage + Exchange charges + SEBI charges)
        """
        turnover = price * quantity
        if turnover <= 0:
            return 0.0

        brokerage = min(20.0, round(turnover * 0.0003, 2))
        stt = round(turnover * 0.00025, 2) if side == OrderSide.SELL else 0.0
        exchange_charges = round(turnover * 0.0000345, 2)
        sebi_charges = round(turnover * 0.000001, 2)
        gst = round((brokerage + exchange_charges + sebi_charges) * 0.18, 2)

        return round(brokerage + stt + exchange_charges + sebi_charges + gst, 2)

    @staticmethod
    def calculate_slippage(
        expected_price: Optional[float],
        actual_price: float,
        quantity: int,
    ) -> float:
        """
        Calculates monetary slippage cost: |actual - expected| * quantity.
        """
        if expected_price is None or expected_price <= 0:
            return 0.0
        return round(abs(actual_price - expected_price) * quantity, 2)

    @staticmethod
    def calculate_net_pnl(
        gross_pnl: float,
        transaction_costs: float,
        slippage: float = 0.0,
    ) -> float:
        """
        Calculates net P&L after deducting transaction fees and execution slippage.
        """
        return round(gross_pnl - transaction_costs - slippage, 2)

    @staticmethod
    def calculate_unrealized_pnl(position: Position, current_price: float) -> float:
        """
        Calculates mark-to-market unrealized P&L on an open position.
        """
        if position.is_flat or current_price <= 0:
            return 0.0
        if position.quantity > 0:
            return round((current_price - position.average_price) * position.quantity, 2)
        else:
            return round((position.average_price - current_price) * abs(position.quantity), 2)
