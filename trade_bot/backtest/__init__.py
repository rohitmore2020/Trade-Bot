"""
VWAP-ORB Backtesting Package.

Provides deterministic event-driven backtesting execution against historical market data.
Reuses existing indicator, scanner, strategy, risk, and portfolio modules.
"""

from trade_bot.backtest.analytics import BacktestAnalytics
from trade_bot.backtest.clock import SimulationClock
from trade_bot.backtest.data_feed import HistoricalDataFeed
from trade_bot.backtest.engine import BacktestEngine
from trade_bot.backtest.interfaces import (
    IBacktestRunner,
    IExecutionSimulator,
    IHistoricalDataFeed,
    ISimulationClock,
)
from trade_bot.backtest.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    DailyPnLSummary,
)
from trade_bot.backtest.simulator import ExecutionSimulator

__all__ = [
    "IBacktestRunner",
    "IExecutionSimulator",
    "IHistoricalDataFeed",
    "ISimulationClock",
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestResult",
    "DailyPnLSummary",
    "SimulationClock",
    "HistoricalDataFeed",
    "ExecutionSimulator",
    "BacktestAnalytics",
    "BacktestEngine",
]
