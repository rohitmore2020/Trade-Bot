"""
Pure Risk Domain Models and Typed Contexts.

Provides strongly typed domain structures for pre-trade risk evaluation,
capital allocation, and exposure monitoring.

Zero infrastructure dependencies; pure business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from trade_bot.domain.enums import MarketRegime, OrderSide, RiskCheckResultStatus
from trade_bot.domain.models import Position
from trade_bot.indicators.vix_filter import VIXRegime


@dataclass(frozen=True, slots=True)
class RiskParameters:
    """
    Approved risk management configuration constraints.
    """
    max_risk_per_trade_pct: float = 0.005       # 0.5% of equity
    max_capital_per_trade_pct: float = 0.20     # 20.0% of equity
    max_open_positions: int = 3                 # 3 concurrent positions
    max_daily_trades: int = 6                   # 6 executed trades per day
    max_daily_loss_pct: float = 0.02            # 2.0% of equity (circuit breaker)
    max_sector_exposure_pct: float = 0.40       # 40.0% of equity per sector
    elevated_vix_multiplier: float = 0.5        # 50% size reduction on elevated VIX
    extreme_vix_multiplier: float = 0.0         # 0% size (trading halted) on extreme VIX
    cautious_regime_multiplier: float = 0.5     # 50% size reduction in cautious regime


@dataclass(frozen=True, slots=True)
class TradeProposal:
    """
    Candidate trade submitted for risk assessment and position sizing.
    """
    symbol: str
    side: OrderSide
    entry_price: float
    stop_loss_price: float
    sector: Optional[str] = None
    lot_size: int = 1
    requested_quantity: Optional[int] = None
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RiskAssessmentContext:
    """
    Explicit market and account state supplied to the risk engine.
    The risk engine does not query databases, APIs, or filesystems.
    """
    equity: float
    available_cash: float
    daily_realized_pnl: float = 0.0
    daily_unrealized_pnl: float = 0.0
    daily_executed_trades: int = 0
    current_positions: Dict[str, Position] = field(default_factory=dict)
    symbol_sector_map: Dict[str, str] = field(default_factory=dict)
    market_regime: Optional[MarketRegime] = None
    vix_regime: Optional[VIXRegime] = None


@dataclass(frozen=True, slots=True)
class RiskDecisionResult:
    """
    Strongly typed, deterministic outcome of risk evaluation.
    """
    status: RiskCheckResultStatus
    is_approved: bool
    reason: str
    rule_name: str
    approved_quantity: int = 0
    risk_per_share: float = 0.0
    total_risk_amount: float = 0.0
    notional_value: float = 0.0
    risk_percentage: float = 0.0
    capital_percentage: float = 0.0
    checks: Dict[str, bool] = field(default_factory=dict)
