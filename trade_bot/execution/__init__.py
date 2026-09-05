"""
Execution Engine and Simulator module for Trade-Bot.
"""

from trade_bot.execution.cost_calculator import TransactionCostCalculator
from trade_bot.execution.engine import ExecutionEngine
from trade_bot.execution.idempotency import IdempotencyManager
from trade_bot.execution.interfaces import IExecutionEngine
from trade_bot.execution.lifecycle_manager import OrderLifecycleManager
from trade_bot.execution.lifecycle_models import (
    ActiveTradeLifecycle,
    TradeLifecycleState,
)
from trade_bot.execution.models import (
    ExecutionSimulatorConfig,
    SimulatorPendingOrder,
    SlippageModelConfig,
    SlippageModelType,
    TransactionCostConfig,
)
from trade_bot.execution.simulator import ExecutionSimulator

__all__ = [
    "ExecutionEngine",
    "IExecutionEngine",
    "IdempotencyManager",
    "OrderLifecycleManager",
    "ActiveTradeLifecycle",
    "TradeLifecycleState",
    "ExecutionSimulator",
    "ExecutionSimulatorConfig",
    "SlippageModelConfig",
    "SlippageModelType",
    "TransactionCostConfig",
    "SimulatorPendingOrder",
    "TransactionCostCalculator",
]

