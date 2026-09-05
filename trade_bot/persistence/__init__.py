"""
Persistence layer module for Trade-Bot.
"""

from trade_bot.persistence.in_memory import (
    InMemoryCandleRepository,
    InMemoryOrderRepository,
    InMemoryTradeRepository,
)
from trade_bot.persistence.interfaces import (
    ICandleRepository,
    IOrderRepository,
    ITradeRepository,
)

__all__ = [
    "ICandleRepository",
    "IOrderRepository",
    "ITradeRepository",
    "InMemoryCandleRepository",
    "InMemoryOrderRepository",
    "InMemoryTradeRepository",
]
