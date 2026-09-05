"""
Data Models and Configurations for Transaction Costs and Slippage.

Strictly separates:
- Brokerage
- Securities Transaction Tax (STT)
- Exchange Transaction Charges (NSE)
- SEBI Turnover Charges
- Stamp Duty
- Goods and Services Tax (GST)
- Execution Slippage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from trade_bot.domain.enums import OrderSide


class SlippageModelType(str, Enum):
    """Supported slippage modeling algorithms."""
    FIXED_TICK = "FIXED_TICK"
    PERCENTAGE = "PERCENTAGE"
    VOLATILITY_ADAPTIVE = "VOLATILITY_ADAPTIVE"
    VOLUME_IMPACT = "VOLUME_IMPACT"


@dataclass(frozen=True, slots=True)
class SlippageConfig:
    """Configurable slippage assumptions."""
    model_type: SlippageModelType = SlippageModelType.FIXED_TICK
    fixed_tick_size: float = 0.05       # Minimum NSE tick: ₹0.05
    percentage: float = 0.0002          # 2 bps (0.02%)
    volatility_mult: float = 0.05       # 5% of bar ATR/range
    volume_participation_limit: float = 0.10  # Max 10% volume per bar
    multiplier: float = 1.0             # General multiplier for stress testing

    @classmethod
    def standard(cls) -> SlippageConfig:
        """Standard production slippage configuration."""
        return cls()

    @classmethod
    def doubled_slippage(cls) -> SlippageConfig:
        """Stress configuration with 2x slippage impact."""
        return cls(multiplier=2.0)

    @classmethod
    def zero_slippage(cls) -> SlippageConfig:
        """Zero slippage model for idealized benchmark testing."""
        return cls(
            fixed_tick_size=0.0,
            percentage=0.0,
            volatility_mult=0.0,
            multiplier=0.0,
        )


@dataclass(frozen=True, slots=True)
class CostModelConfig:
    """
    Configurable Indian equity cash intraday statutory tax and fee parameters.
    Default parameters adhere to standard Indian NSE statutory tax rates.
    """
    version: str = "NSE_EQUITY_2024_V1"
    brokerage_per_order: float = 20.0        # Max flat brokerage per executed order (₹20)
    brokerage_pct_cap: float = 0.0003         # 0.03% cap on turnover
    stt_sell_pct: float = 0.00025             # 0.025% on sell side for equity intraday
    exchange_turnover_pct: float = 0.0000345  # 0.00345% NSE exchange transaction fee
    sebi_turnover_pct: float = 0.000001       # ₹10 per crore (0.0001%) SEBI turnover charge
    gst_pct: float = 0.18                     # 18% GST on (brokerage + exchange + SEBI fees)
    stamp_duty_buy_pct: float = 0.00003       # 0.003% on buy side stamp duty
    cost_multiplier: float = 1.0              # Multiplier applied for stress testing

    @classmethod
    def standard(cls) -> CostModelConfig:
        """Standard Indian NSE cash equity intraday configuration."""
        return cls()

    @classmethod
    def stress_plus_50_pct(cls) -> CostModelConfig:
        """Stress configuration with +50% costs across all statutory levies and brokerage."""
        return cls(
            version="NSE_EQUITY_STRESS_PLUS_50",
            brokerage_per_order=30.0,
            brokerage_pct_cap=0.00045,
            stt_sell_pct=0.000375,
            exchange_turnover_pct=0.00005175,
            sebi_turnover_pct=0.0000015,
            gst_pct=0.18,  # Tax rate itself, but base is 1.5x
            stamp_duty_buy_pct=0.000045,
            cost_multiplier=1.5,
        )

    @classmethod
    def with_multiplier(cls, multiplier: float) -> CostModelConfig:
        """Custom scaled configuration for scenario analysis."""
        return cls(
            version=f"NSE_EQUITY_CUSTOM_{multiplier:.2f}X",
            brokerage_per_order=round(20.0 * multiplier, 2),
            brokerage_pct_cap=round(0.0003 * multiplier, 6),
            stt_sell_pct=round(0.00025 * multiplier, 6),
            exchange_turnover_pct=round(0.0000345 * multiplier, 8),
            sebi_turnover_pct=round(0.000001 * multiplier, 8),
            gst_pct=0.18,
            stamp_duty_buy_pct=round(0.00003 * multiplier, 6),
            cost_multiplier=multiplier,
        )

    @classmethod
    def zero_cost(cls) -> CostModelConfig:
        """Hypothetical zero-cost configuration for frictionless comparisons."""
        return cls(
            version="ZERO_COST_IDEAL",
            brokerage_per_order=0.0,
            brokerage_pct_cap=0.0,
            stt_sell_pct=0.0,
            exchange_turnover_pct=0.0,
            sebi_turnover_pct=0.0,
            gst_pct=0.0,
            stamp_duty_buy_pct=0.0,
            cost_multiplier=0.0,
        )


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """Detailed itemized transaction cost breakdown for a single fill."""
    turnover: float
    side: OrderSide
    brokerage: float
    stt: float
    exchange_charges: float
    sebi_charges: float
    stamp_duty: float
    gst: float
    total_statutory_taxes: float
    total_costs: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "turnover": self.turnover,
            "brokerage": self.brokerage,
            "stt": self.stt,
            "exchange_charges": self.exchange_charges,
            "sebi_charges": self.sebi_charges,
            "stamp_duty": self.stamp_duty,
            "gst": self.gst,
            "total_statutory_taxes": self.total_statutory_taxes,
            "total_costs": self.total_costs,
        }


@dataclass(frozen=True, slots=True)
class RoundTripCostBreakdown:
    """Detailed round-trip transaction costs across entry and exit legs."""
    entry_cost: CostBreakdown
    exit_cost: CostBreakdown
    total_turnover: float
    total_brokerage: float
    total_stt: float
    total_exchange_charges: float
    total_sebi_charges: float
    total_stamp_duty: float
    total_gst: float
    total_statutory_taxes: float
    total_slippage: float
    total_frictional_costs: float
    cost_basis_points: float  # (total_frictional_costs / total_turnover) * 10000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_leg": self.entry_cost.to_dict(),
            "exit_leg": self.exit_cost.to_dict(),
            "total_turnover": self.total_turnover,
            "total_brokerage": self.total_brokerage,
            "total_stt": self.total_stt,
            "total_exchange_charges": self.total_exchange_charges,
            "total_sebi_charges": self.total_sebi_charges,
            "total_stamp_duty": self.total_stamp_duty,
            "total_gst": self.total_gst,
            "total_statutory_taxes": self.total_statutory_taxes,
            "total_slippage": self.total_slippage,
            "total_frictional_costs": self.total_frictional_costs,
            "cost_basis_points": self.cost_basis_points,
        }


@dataclass(frozen=True, slots=True)
class AggregateCostReport:
    """Multi-trade aggregated transaction cost report."""
    total_fills: int
    total_turnover: float
    total_brokerage: float
    total_stt: float
    total_exchange_charges: float
    total_sebi_charges: float
    total_stamp_duty: float
    total_gst: float
    total_statutory_taxes: float
    total_slippage: float
    total_costs: float
    effective_friction_pct: float  # (total_costs / total_turnover) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_fills": self.total_fills,
            "total_turnover": self.total_turnover,
            "total_brokerage": self.total_brokerage,
            "total_stt": self.total_stt,
            "total_exchange_charges": self.total_exchange_charges,
            "total_sebi_charges": self.total_sebi_charges,
            "total_stamp_duty": self.total_stamp_duty,
            "total_gst": self.total_gst,
            "total_statutory_taxes": self.total_statutory_taxes,
            "total_slippage": self.total_slippage,
            "total_costs": self.total_costs,
            "effective_friction_pct": self.effective_friction_pct,
        }
