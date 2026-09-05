"""
Risk Management module for Trade-Bot.
"""

from trade_bot.risk.interfaces import IRiskManager, IRiskRule
from trade_bot.risk.manager import RiskManager
from trade_bot.risk.rules import (
    AvailableCashRule,
    MaxDailyLossRule,
    MaxLossPerTradeRule,
    MaxOpenPositionsRule,
    MaxPositionSizeRule,
)

__all__ = [
    "AvailableCashRule",
    "IRiskManager",
    "IRiskRule",
    "MaxDailyLossRule",
    "MaxLossPerTradeRule",
    "MaxOpenPositionsRule",
    "MaxPositionSizeRule",
    "RiskManager",
]
