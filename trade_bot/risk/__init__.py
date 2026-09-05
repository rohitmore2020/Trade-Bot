"""
Risk Management module for Trade-Bot.
"""

from trade_bot.risk.capital_exposure_checker import CapitalExposureChecker
from trade_bot.risk.daily_loss_checker import DailyLossChecker
from trade_bot.risk.decision_engine import RiskDecisionEngine
from trade_bot.risk.interfaces import IRiskManager, IRiskRule
from trade_bot.risk.manager import RiskManager
from trade_bot.risk.models import (
    RiskAssessmentContext,
    RiskDecisionResult,
    RiskParameters,
    TradeProposal,
)
from trade_bot.risk.position_sizer import PositionSizer
from trade_bot.risk.rules import (
    AvailableCashRule,
    MaxDailyLossRule,
    MaxLossPerTradeRule,
    MaxOpenPositionsRule,
    MaxPositionSizeRule,
)
from trade_bot.risk.sector_exposure_checker import SectorExposureChecker
from trade_bot.risk.trade_limit_checker import TradeLimitChecker

__all__ = [
    "AvailableCashRule",
    "CapitalExposureChecker",
    "DailyLossChecker",
    "IRiskManager",
    "IRiskRule",
    "MaxDailyLossRule",
    "MaxLossPerTradeRule",
    "MaxOpenPositionsRule",
    "MaxPositionSizeRule",
    "PositionSizer",
    "RiskAssessmentContext",
    "RiskDecisionEngine",
    "RiskDecisionResult",
    "RiskManager",
    "RiskParameters",
    "SectorExposureChecker",
    "TradeLimitChecker",
    "TradeProposal",
]
