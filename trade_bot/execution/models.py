"""
Execution Simulation Configuration and Domain Models.

Defines configurable slippage, transaction cost, and execution models.
Decoupled from strategy and portfolio management layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType
from trade_bot.domain.models import Order


class SlippageModelType(str, Enum):
    """Supported slippage modeling algorithms."""
    FIXED_TICK = "FIXED_TICK"
    PERCENTAGE = "PERCENTAGE"
    VOLATILITY_ADAPTIVE = "VOLATILITY_ADAPTIVE"
    VOLUME_IMPACT = "VOLUME_IMPACT"


@dataclass(frozen=True, slots=True)
class SlippageModelConfig:
    """Configurable execution slippage parameters."""
    model_type: SlippageModelType = SlippageModelType.FIXED_TICK
    fixed_tick_size: float = 0.05  # Default NSE minimum tick = 0.05 INR
    percentage: float = 0.0002     # Default 2 bps (0.02%)
    volatility_mult: float = 0.05  # 5% of bar ATR/range
    volume_participation_limit: float = 0.10  # Max 10% of bar volume per fill
    enable_limit_slippage: bool = False       # Limit orders experience zero adverse slippage


@dataclass(frozen=True, slots=True)
class TransactionCostConfig:
    """
    Configurable Indian equity intraday transaction cost parameters.
    Default parameters adhere to standard Indian NSE statutory tax rates.
    """
    brokerage_per_order: float = 20.0       # Max Rs 20 per executed order
    brokerage_pct_cap: float = 0.0003        # 0.03% cap on turnover
    stt_intraday_sell_pct: float = 0.00025   # 0.025% on sell side for equity intraday
    exchange_turnover_pct: float = 0.0000345 # 0.00345% NSE exchange transaction fee
    sebi_turnover_pct: float = 0.000001      # Rs 10 per crore (0.0001%) SEBI turnover charge
    gst_pct: float = 0.18                    # 18% GST on (brokerage + exchange + SEBI fees)
    stamp_duty_buy_pct: float = 0.00003      # 0.003% on buy side stamp duty


@dataclass(frozen=True, slots=True)
class ExecutionSimulatorConfig:
    """Master configuration for the standalone execution simulator."""
    slippage: SlippageModelConfig = field(default_factory=SlippageModelConfig)
    costs: TransactionCostConfig = field(default_factory=TransactionCostConfig)
    default_timeout_bars: int = 1            # Order cancellation after N bars if unfilled
    partial_fills_enabled: bool = True        # Enable volume participation capping
    conservative_collision_policy: bool = True  # Stop loss takes priority over target if both touched


@dataclass
class SimulatorPendingOrder:
    """Internal tracking representation of an active order in the simulator."""
    order: Order
    placed_at: datetime
    bars_active: int = 0
    timeout_bars: int = 1
    filled_quantity: int = 0
    remaining_quantity: int = 0
    stop_price: Optional[float] = None
    target_price: Optional[float] = None

    def __post_init__(self) -> None:
        if self.remaining_quantity == 0:
            self.remaining_quantity = self.order.quantity
