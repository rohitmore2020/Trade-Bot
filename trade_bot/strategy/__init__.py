"""
Strategy module for Trade-Bot.
"""

from trade_bot.strategy.base import IStrategy, StrategyContext
from trade_bot.strategy.engine import VWAPORBStrategyEngine
from trade_bot.strategy.entry_rules import (
    EntryEvaluationResult,
    LongEntryRule,
    ShortEntryRule,
)
from trade_bot.strategy.exit_rules import (
    ExitEvaluationResult,
    ExitEvaluator,
    InitialStopEvaluator,
    TimeExitEvaluator,
    TrailingStopEvaluator,
    VwapExitEvaluator,
)
from trade_bot.strategy.models import (
    ActiveTradeState,
    PositionSizingResult,
    SignalEvaluationResult,
    SignalTriggerReason,
    StrategyMarketInput,
    TradeIntent,
    UniverseCandidate,
    VwapOrbSignal,
    VwapOrbStrategyConfig,
)
from trade_bot.strategy.pure_strategy import VwapOrbPureStrategy
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
from trade_bot.strategy.signal_builder import SignalBuilder
from trade_bot.strategy.state import (
    ExitReason,
    PositionStatus,
    StrategyTradeState,
)

__all__ = [
    "ActiveTradeState",
    "EntryEvaluationResult",
    "ExitEvaluationResult",
    "ExitEvaluator",
    "ExitReason",
    "IStrategy",
    "InitialStopEvaluator",
    "LongEntryRule",
    "MarketRegimeRule",
    "PositionSizer",
    "PositionSizingResult",
    "PositionStatus",
    "SessionRiskGuard",
    "ShortEntryRule",
    "SignalBuilder",
    "SignalEvaluationResult",
    "SignalTriggerReason",
    "StopLossRule",
    "StrategyContext",
    "StrategyMarketInput",
    "StrategyRegistry",
    "StrategyTradeState",
    "TimeExitEvaluator",
    "TimeExitRule",
    "TradeIntent",
    "TrailingStopEvaluator",
    "TrailingStopRule",
    "UniverseCandidate",
    "VWAPORBStrategyEngine",
    "VwapExitEvaluator",
    "VwapExitRule",
    "VwapOrbPureStrategy",
    "VwapOrbSignal",
    "VwapOrbSignalRule",
    "VwapOrbStrategyConfig",
]
