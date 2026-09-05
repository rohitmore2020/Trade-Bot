"""
Market Data handling, aggregation, and streaming feed module.
"""

from trade_bot.data.aggregator import TimeframeCandleAggregator
from trade_bot.data.interfaces import (
    ICandleAggregator,
    IHistoricalDataLoader,
    IMarketDataProvider,
)
from trade_bot.data.memory_data_feed import InMemoryMarketDataFeed

__all__ = [
    "ICandleAggregator",
    "IHistoricalDataLoader",
    "IMarketDataProvider",
    "InMemoryMarketDataFeed",
    "TimeframeCandleAggregator",
]
