"""
Broker Adapters module for Trade-Bot.
"""

from trade_bot.broker.backtest_adapter import BacktestBrokerAdapter
from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.broker.paper_adapter import PaperBrokerAdapter
from trade_bot.broker.paper_models import (
    ExecutionLogEntry,
    ExecutionStage,
    PaperBrokerConfig,
)
from trade_bot.broker.upstox_adapter import UpstoxBrokerAdapter

__all__ = [
    "BacktestBrokerAdapter",
    "IBrokerAdapter",
    "PaperBrokerAdapter",
    "UpstoxBrokerAdapter",
    "ExecutionStage",
    "ExecutionLogEntry",
    "PaperBrokerConfig",
]

