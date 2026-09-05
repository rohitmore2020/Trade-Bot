"""
Transaction Cost and Slippage Model Interfaces.

Defines the core abstractions for financial transaction costs and slippage estimation
for the backtester and execution simulator.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import Candle
from trade_bot.costs.models import (
    AggregateCostReport,
    CostBreakdown,
    CostModelConfig,
    RoundTripCostBreakdown,
    SlippageConfig,
)


@runtime_checkable
class ISlippageModel(Protocol):
    """Protocol for calculating execution price slippage."""

    @property
    def config(self) -> SlippageConfig:
        """Returns the slippage configuration."""
        ...

    def calculate_slippage_price(
        self,
        price: float,
        side: OrderSide,
        candle: Optional[Candle] = None,
    ) -> float:
        """
        Calculates the execution price adjusted for adverse slippage.
        For BUY: price + slippage
        For SELL: max(0.05, price - slippage)
        """
        ...

    def calculate_slippage_cost(
        self,
        expected_price: Optional[float],
        actual_price: float,
        quantity: int,
    ) -> float:
        """Calculates total monetary value of execution slippage: |actual - expected| * qty."""
        ...


@runtime_checkable
class ICostModel(Protocol):
    """Protocol for calculating exchange fees, statutory taxes, and broker commissions."""

    @property
    def version(self) -> str:
        """Returns the cost model version string."""
        ...

    @property
    def config(self) -> CostModelConfig:
        """Returns the cost model configuration."""
        ...

    def calculate_per_order_cost(
        self,
        price: float,
        quantity: int,
        side: OrderSide,
    ) -> CostBreakdown:
        """
        Calculates itemized transaction costs for an individual order execution fill.
        """
        ...

    def calculate_round_trip_cost(
        self,
        entry_price: float,
        exit_price: float,
        quantity: int,
        entry_side: OrderSide = OrderSide.BUY,
        slippage: float = 0.0,
    ) -> RoundTripCostBreakdown:
        """
        Calculates complete round-trip costs across both entry and exit legs.
        """
        ...

    def calculate_aggregate_report(
        self,
        breakdowns: List[CostBreakdown],
        total_slippage: float = 0.0,
    ) -> AggregateCostReport:
        """
        Aggregates multiple individual order cost breakdowns into a comprehensive report.
        """
        ...
