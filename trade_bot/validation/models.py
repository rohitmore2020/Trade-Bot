"""
Domain Models and Data Containers for Strategy Robustness Testing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional


class RobustnessVerdict(str, Enum):
    """Final robustness evaluation status."""
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class ExperimentSummary:
    """Standardized record for any robustness experiment."""
    experiment_name: str
    dataset_period: str
    strategy_version: str
    parameters: Dict[str, Any]
    number_of_trades: int
    profit_factor: float
    expectancy: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    max_losing_streak: int
    net_pnl: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_name": self.experiment_name,
            "dataset_period": self.dataset_period,
            "strategy_version": self.strategy_version,
            "parameters": self.parameters,
            "number_of_trades": self.number_of_trades,
            "profit_factor": self.profit_factor,
            "expectancy": self.expectancy,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "win_rate": self.win_rate,
            "max_losing_streak": self.max_losing_streak,
            "net_pnl": self.net_pnl,
        }


@dataclass(frozen=True, slots=True)
class MonteCarloSimulationResult:
    """Aggregated outcome of trade sequence randomization."""
    iterations: int
    initial_capital: float
    mean_terminal_equity: float
    median_terminal_equity: float
    p5_terminal_equity: float
    p25_terminal_equity: float
    p75_terminal_equity: float
    p95_terminal_equity: float
    p99_terminal_equity: float
    median_max_drawdown_pct: float
    p95_max_drawdown_pct: float
    worst_case_drawdown_pct: float
    median_losing_streak: int
    p95_losing_streak: int
    max_losing_streak: int
    probability_of_loss: float
    risk_of_ruin_pct: float  # Probability of experiencing > 20% drawdown


@dataclass(frozen=True, slots=True)
class WalkForwardFoldResult:
    """Individual in-sample and out-of-sample window result."""
    fold_index: int
    in_sample_period: str
    out_of_sample_period: str
    is_profit_factor: float
    oos_profit_factor: float
    is_net_pnl: float
    oos_net_pnl: float
    is_trades: int
    oos_trades: int
    walk_forward_efficiency: float  # (OOS Annualized Return / IS Annualized Return)


@dataclass(frozen=True, slots=True)
class WalkForwardAnalysisResult:
    """Overall multi-fold walk-forward validation outcome."""
    folds: List[WalkForwardFoldResult]
    mean_wfe: float
    median_wfe: float
    profitable_oos_folds_ratio: float
    consistency_score: float


@dataclass(frozen=True, slots=True)
class ParameterVariationResult:
    """Single parameter point performance."""
    parameter_name: str
    parameter_value: Any
    summary: ExperimentSummary
    neighbor_deviation_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class ParameterSensitivityResult:
    """Sensitivity results for a single parameter sweep."""
    parameter_name: str
    default_value: Any
    tested_values: List[Any]
    variations: List[ParameterVariationResult]
    profit_factor_cv: float  # Coefficient of variation (std / mean)
    is_stable: bool
    cliff_detected: bool
    cliff_details: Optional[str] = None


@dataclass(frozen=True, slots=True)
class StressTestResult:
    """Outcomes across cost, slippage, and stock stress tests."""
    cost_stress_summaries: Dict[str, ExperimentSummary]
    slippage_stress_summaries: Dict[str, ExperimentSummary]
    stock_pnl_distribution: Dict[str, float]
    top_stock_concentration_pct: float
    cost_breakeven_multiplier: float
    slippage_breakeven_multiplier: float


@dataclass
class RobustnessEvaluationReport:
    """Master synthesis and scorecard across all 9 validation dimensions."""
    strategy_name: str
    timestamp: str
    baseline: ExperimentSummary
    oos: ExperimentSummary
    walk_forward: WalkForwardAnalysisResult
    monte_carlo: MonteCarloSimulationResult
    parameter_sensitivities: List[ParameterSensitivityResult]
    stress_testing: StressTestResult
    regime_summaries: Dict[str, ExperimentSummary]
    criteria_scorecard: Dict[str, bool]
    verdict: RobustnessVerdict
    verdict_rationale: str
    flags: List[str] = field(default_factory=list)
