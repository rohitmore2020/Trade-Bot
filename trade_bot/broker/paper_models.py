"""
Paper Trading Execution Domain Models and Logging.

Provides execution stage enums, structured audit log entries, and configuration
for realistic paper execution simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType


class ExecutionStage(str, Enum):
    """Execution pipeline stages distinguishing request, acceptance, fill, and position."""
    ORDER_REQUEST = "ORDER_REQUEST"
    ORDER_ACCEPTANCE = "ORDER_ACCEPTANCE"
    ORDER_REJECTION = "ORDER_REJECTION"
    ORDER_WORKING = "ORDER_WORKING"
    ORDER_PARTIAL_FILL = "ORDER_PARTIAL_FILL"
    ORDER_FILL = "ORDER_FILL"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    POSITION_UPDATE = "POSITION_UPDATE"


@dataclass(frozen=True)
class ExecutionLogEntry:
    """
    Structured immutable execution log entry recording every transition
    through the broker execution lifecycle.
    """
    timestamp: datetime
    stage: ExecutionStage
    client_order_id: str
    broker_order_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[OrderSide] = None
    order_type: Optional[OrderType] = None
    quantity: int = 0
    filled_quantity: int = 0
    price: Optional[float] = None
    fill_price: Optional[float] = None
    status: Optional[OrderStatus] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PaperBrokerConfig:
    """Configuration options for paper-trading execution simulator."""
    initial_capital: float = 100000.0
    simulated_latency_ms: float = 0.0
    default_slippage_pct: float = 0.0005  # 0.05% adverse slippage
    enable_partial_fills: bool = False
    partial_fill_ratio: float = 0.50  # Fill 50% first if partial fills enabled
    brokerage_per_order: float = 20.0
    stt_pct: float = 0.00025
    gst_pct: float = 0.18
    txn_charges_pct: float = 0.0000345
    sebi_charges_pct: float = 0.000001
    stamp_duty_pct: float = 0.00003
