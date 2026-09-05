"""
Configurable Transaction Cost Calculator.

Calculates statutory exchange fees, taxes, and brokerages for Indian equities.
Fully configurable parameters; never silently assumes zero costs.
"""

from __future__ import annotations

from typing import Optional, Tuple

from trade_bot.costs.cost_model import IndianEquityCostModel
from trade_bot.costs.models import CostModelConfig
from trade_bot.domain.enums import OrderSide
from trade_bot.execution.models import TransactionCostConfig


class TransactionCostCalculator:
    """
    Computes Indian equity transaction charges and brokerage based on configuration.
    Adapts to the Phase 13 IndianEquityCostModel.
    """

    def __init__(self, config: Optional[TransactionCostConfig] = None) -> None:
        self.config = config or TransactionCostConfig()
        cost_cfg = CostModelConfig(
            brokerage_per_order=self.config.brokerage_per_order,
            brokerage_pct_cap=self.config.brokerage_pct_cap,
            stt_sell_pct=self.config.stt_intraday_sell_pct,
            exchange_turnover_pct=self.config.exchange_turnover_pct,
            sebi_turnover_pct=self.config.sebi_turnover_pct,
            gst_pct=self.config.gst_pct,
            stamp_duty_buy_pct=self.config.stamp_duty_buy_pct,
        )
        self._model = IndianEquityCostModel(config=cost_cfg)

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
        bd = self._model.calculate_per_order_cost(price=price, quantity=quantity, side=side)
        return bd.brokerage, bd.total_statutory_taxes

    def calculate_total(
        self,
        price: float,
        quantity: int,
        side: OrderSide,
    ) -> float:
        """Convenience method returning total all-inclusive transaction cost."""
        bd = self._model.calculate_per_order_cost(price=price, quantity=quantity, side=side)
        return bd.total_costs
