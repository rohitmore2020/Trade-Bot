"""
Portfolio Management module for Trade-Bot.
"""

from trade_bot.portfolio.interfaces import IPortfolioManager
from trade_bot.portfolio.manager import PortfolioManager

__all__ = [
    "IPortfolioManager",
    "PortfolioManager",
]
