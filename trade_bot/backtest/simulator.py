"""
Backtest Execution Simulator Module.

Re-exports the standalone ExecutionSimulator from trade_bot.execution.simulator.
Maintains clean architectural decoupling while preserving backwards compatibility.
"""

from trade_bot.execution.simulator import ExecutionSimulator
from trade_bot.execution.models import (
    ExecutionSimulatorConfig,
    SimulatorPendingOrder,
    SlippageModelConfig,
    SlippageModelType,
    TransactionCostConfig,
)

# Aliases for backtesting backwards compatibility
ActiveStopLoss = SimulatorPendingOrder
PendingLimitOrder = SimulatorPendingOrder

__all__ = [
    "ExecutionSimulator",
    "ExecutionSimulatorConfig",
    "SlippageModelConfig",
    "SlippageModelType",
    "TransactionCostConfig",
    "SimulatorPendingOrder",
    "ActiveStopLoss",
    "PendingLimitOrder",
]
