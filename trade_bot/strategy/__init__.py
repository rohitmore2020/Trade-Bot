"""
Strategy module for Trade-Bot.
"""

from trade_bot.strategy.base import IStrategy, StrategyContext
from trade_bot.strategy.engine import VWAPORBStrategyEngine
from trade_bot.strategy.models import (
    ActiveTradeState,
    PositionSizingResult,
    SignalEvaluationResult,
    SignalTriggerReason,
    UniverseCandidate,
    VwapOrbSignal,
    VwapOrbStrategyConfig,
)
from trade_bot.strategy.registry import StrategyRegistry
from trade_bot.strategy.rules import (
    MarketRegimeRule,
    PositionSizer,
    SessionRiskGuard,
    StopLossRule,
    TimeExitRule,
    TrailingStopRule,
    VwapExitRule,
    VwapOrbSignalRule,
)

__all__ = [
    "ActiveTradeState",
    "IStrategy",
    "MarketRegimeRule",
    "PositionSizer",
    "PositionSizingResult",
    "SessionRiskGuard",
    "SignalEvaluationResult",
    "SignalTriggerReason",
    "StopLossRule",
    "StrategyContext",
    "StrategyRegistry",
    "TimeExitRule",
    "TrailingStopRule",
    "UniverseCandidate",
    "VWAPORBStrategyEngine",
    "VwapExitRule",
    "VwapOrbSignal",
    "VwapOrbSignalRule",
    "VwapOrbStrategyConfig",
]
