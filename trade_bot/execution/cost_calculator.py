"""
Configurable Transaction Cost Calculator.

Calculates statutory exchange fees, taxes, and brokerages for Indian equities.
Fully configurable parameters; never silently assumes zero costs.
"""

from __future__ import annotations

from typing import Optional, Tuple

from trade_bot.domain.enums import OrderSide
from trade_bot.execution.models import TransactionCostConfig


class TransactionCostCalculator:
    """
    Computes Indian equity transaction charges and brokerage based on configuration.
    """

    def __init__(self, config: Optional[TransactionCostConfig] = None) -> None:
        self.config = config or TransactionCostConfig()

    def calculate(
        self,
        price: float,
        quantity: int,
        side: OrderSide,
    ) -> Tuple[float, float]:
        """
        Computes statutory fees for a fill.
        Returns: (brokerage, statutory_taxes)
        """
        turnover = round(price * quantity, 2)
        if turnover <= 0.0:
            return 0.0, 0.0

        # Brokerage: min(flat_fee, pct_cap * turnover)
        pct_brokerage = turnover * self.config.brokerage_pct_cap
        brokerage = min(self.config.brokerage_per_order, pct_brokerage)

        # STT: 0.025% on sell side for intraday equities
        stt = turnover * self.config.stt_intraday_sell_pct if side == OrderSide.SELL else 0.0

        # Exchange Transaction Charges
        exchange_turnover_fee = turnover * self.config.exchange_turnover_pct

        # SEBI Turnover Charges
        sebi_fee = turnover * self.config.sebi_turnover_pct

        # GST: 18% on (Brokerage + Exchange Fee + SEBI Fee)
        gst = (brokerage + exchange_turnover_fee + sebi_fee) * self.config.gst_pct

        # Stamp Duty: 0.003% on buy side only
        stamp_duty = turnover * self.config.stamp_duty_buy_pct if side == OrderSide.BUY else 0.0

        statutory_taxes = round(stt + exchange_turnover_fee + sebi_fee + gst + stamp_duty, 2)
        return round(brokerage, 2), statutory_taxes

    def calculate_total(
        self,
        price: float,
        quantity: int,
        side: OrderSide,
    ) -> float:
        """Convenience method returning total all-inclusive transaction cost."""
        b, t = self.calculate(price, quantity, side)
        return round(b + t, 2)
