"""
Reusable Analytics Layer for Trade-Bot.
"""

from trade_bot.analytics.breakdowns import BreakdownEngine
from trade_bot.analytics.drawdown import DrawdownCalculator
from trade_bot.analytics.execution_stats import ExecutionStatsCalculator
from trade_bot.analytics.models import (
    ComprehensiveReport,
    DrawdownMetrics,
    ExecutionMetrics,
    GroupBreakdown,
    PnLMetrics,
    ReturnMetrics,
    RiskMetrics,
    TradeStatsMetrics,
)
from trade_bot.analytics.pnl import PnLAnalyticsCalculator
from trade_bot.analytics.reporter import PerformanceReporter
from trade_bot.analytics.returns import ReturnsCalculator
from trade_bot.analytics.risk_metrics import RiskMetricsCalculator
from trade_bot.analytics.trade_stats import TradeStatsCalculator

__all__ = [
    "ComprehensiveReport",
    "ReturnMetrics",
    "PnLMetrics",
    "DrawdownMetrics",
    "TradeStatsMetrics",
    "RiskMetrics",
    "ExecutionMetrics",
    "GroupBreakdown",
    "ReturnsCalculator",
    "PnLAnalyticsCalculator",
    "DrawdownCalculator",
    "TradeStatsCalculator",
    "RiskMetricsCalculator",
    "ExecutionStatsCalculator",
    "BreakdownEngine",
    "PerformanceReporter",
]
