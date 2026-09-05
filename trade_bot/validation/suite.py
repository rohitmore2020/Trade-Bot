"""
Robustness Test Suite and Scorecard Evaluator.

Orchestrates all 9 robustness experiments:
1. In-sample baseline testing
2. Out-of-sample holdout testing
3. Walk-forward validation
4. Parameter sensitivity & cliff detection
5. Monte Carlo trade-sequence simulation
6. Market-regime analysis
7. Stock robustness
8. Transaction-cost stress
9. Slippage stress

Applies predefined quantitative acceptance criteria and issues an unvarnished PASS / FAIL / INCONCLUSIVE verdict.
Generates all 7 required markdown artifacts in docs/validation/.
"""

from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Dict, List, Optional

from trade_bot.portfolio.models import CompletedTrade
from trade_bot.validation.models import (
    ExperimentSummary,
    MonteCarloSimulationResult,
    ParameterSensitivityResult,
    RobustnessEvaluationReport,
    RobustnessVerdict,
    StressTestResult,
    WalkForwardAnalysisResult,
)
from trade_bot.validation.monte_carlo import MonteCarloSimulator
from trade_bot.validation.sensitivity import ParameterSensitivityAnalyzer
from trade_bot.validation.stress import StressTestEngine
from trade_bot.validation.walk_forward import WalkForwardValidator


class RobustnessSuite:
    """
    Executes and synthesizes the full battery of robustness tests.
    """

    @classmethod
    def evaluate(
        cls,
        baseline_summary: ExperimentSummary,
        oos_summary: ExperimentSummary,
        all_trades: List[CompletedTrade],
        walk_forward_folds: List[Dict[str, Any]],
        parameter_sweeps: List[Dict[str, Any]],
        regime_summaries: Dict[str, ExperimentSummary],
        initial_capital: float = 100_000.0,
        monte_carlo_iterations: int = 1_000,
    ) -> RobustnessEvaluationReport:
        """
        Synthesizes validation results and evaluates acceptance criteria.
        """
        # 1. Monte Carlo Simulation
        trade_pnls = [t.net_pnl for t in all_trades]
        mc_result = MonteCarloSimulator.simulate(
            trade_pnls=trade_pnls,
            initial_capital=initial_capital,
            iterations=monte_carlo_iterations,
        )

        # 2. Walk-Forward Validation
        wf_result = WalkForwardValidator.evaluate_folds(walk_forward_folds)

        # 3. Parameter Sensitivity Sweeps
        sensitivities: List[ParameterSensitivityResult] = []
        for sweep in parameter_sweeps:
            p_name = sweep["parameter_name"]
            d_val = sweep["default_value"]
            v_data = sweep["variations"]
            sens = ParameterSensitivityAnalyzer.analyze_parameter(p_name, d_val, v_data)
            sensitivities.append(sens)

        # 4. Stress Testing (Costs, Slippage, Stock Concentration)
        stress_result = StressTestEngine.evaluate_stress(all_trades)

        # 5. Predefined Acceptance Criteria Evaluation
        c1_oos_pf = oos_summary.profit_factor >= 1.20
        c2_wfe = wf_result.mean_wfe >= 0.50
        c3_param_stability = all(s.is_stable for s in sensitivities)
        c4_mc_tail_risk = mc_result.p95_max_drawdown_pct <= 15.0 and mc_result.risk_of_ruin_pct <= 1.0
        profitable_regimes = sum(1 for reg_sum in regime_summaries.values() if reg_sum.net_pnl > 0)
        c5_regime_versatility = profitable_regimes >= 2
        c6_stock_diversification = stress_result.top_stock_concentration_pct < 60.0
        c7_frictional_survival = (
            stress_result.cost_stress_summaries.get("costs_1.50x", baseline_summary).net_pnl > 0
            and stress_result.slippage_stress_summaries.get("slippage_2.00x", baseline_summary).net_pnl > 0
        )

        criteria = {
            "1. Out-of-Sample Profit Factor >= 1.20": c1_oos_pf,
            "2. Walk-Forward Efficiency (WFE) >= 50%": c2_wfe,
            "3. Parameter Stability (No Cliffs, CV <= 0.40)": c3_param_stability,
            "4. Monte Carlo 95th Percentile Drawdown <= 15%": c4_mc_tail_risk,
            "5. Multi-Regime Profitability (>= 2 Regimes)": c5_regime_versatility,
            "6. Stock Diversification (Top Stock < 60% PnL)": c6_stock_diversification,
            "7. Frictional Stress Survival (+50% Costs, 2x Slippage)": c7_frictional_survival,
        }

        # Flags & Diagnostics
        flags: List[str] = []
        if not c1_oos_pf:
            flags.append(f"OOS Fragility: Out-of-sample PF ({oos_summary.profit_factor:.2f}) failed target threshold 1.20")
        if not c2_wfe:
            flags.append(f"Overfitting Indicator: Walk-Forward Efficiency ({wf_result.mean_wfe*100:.1f}%) < 50%")
        if not c3_param_stability:
            cliffs = [s.cliff_details for s in sensitivities if s.cliff_detected and s.cliff_details]
            flags.append(f"Parameter Instability: Fragile parameters detected ({'; '.join(cliffs)})")
        if not c4_mc_tail_risk:
            flags.append(f"Sequence Risk: Monte Carlo 95th percentile DD ({mc_result.p95_max_drawdown_pct:.1f}%) exceeds 15%")
        if not c5_regime_versatility:
            flags.append("Regime Dependency: Strategy is profitable in fewer than 2 market regimes")
        if not c6_stock_diversification:
            flags.append(f"Stock Concentration: Top stock generates {stress_result.top_stock_concentration_pct:.1f}% of total net profits")
        if not c7_frictional_survival:
            flags.append("Cost / Slippage Vulnerability: Strategy collapses into net losses under 1.5x statutory costs or 2x slippage")

        # Determine Verdict
        passed_count = sum(1 for passed in criteria.values() if passed)
        if len(all_trades) < 30:
            verdict = RobustnessVerdict.INCONCLUSIVE
            verdict_rationale = f"Sample size ({len(all_trades)} trades) is insufficient for statistical confidence (< 30 trades)."
        elif passed_count == len(criteria):
            verdict = RobustnessVerdict.PASS
            verdict_rationale = "Strategy satisfies all 7 quantitative robustness criteria across In-Sample, Out-of-Sample, Walk-Forward, Monte Carlo, and Stress dimensions."
        elif passed_count >= 5 and c1_oos_pf:
            verdict = RobustnessVerdict.INCONCLUSIVE
            verdict_rationale = f"Strategy passed {passed_count}/7 criteria. While OOS is profitable, secondary robustness constraints tripped."
        else:
            verdict = RobustnessVerdict.FAIL
            verdict_rationale = f"Strategy failed {len(criteria) - passed_count}/7 criteria. Identified critical vulnerabilities: {'; '.join(flags[:2])}."

        return RobustnessEvaluationReport(
            strategy_name=baseline_summary.strategy_version,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            baseline=baseline_summary,
            oos=oos_summary,
            walk_forward=wf_result,
            monte_carlo=mc_result,
            parameter_sensitivities=sensitivities,
            stress_testing=stress_result,
            regime_summaries=regime_summaries,
            criteria_scorecard=criteria,
            verdict=verdict,
            verdict_rationale=verdict_rationale,
            flags=flags,
        )

    # =========================================================================
    # Report Markdown Generators
    # =========================================================================

    @staticmethod
    def generate_baseline_md(report: RobustnessEvaluationReport) -> str:
        b = report.baseline
        return f"""# In-Sample Baseline Performance: VWAP-ORB

## Dataset & Configuration
- **Dataset Period**: {b.dataset_period}
- **Strategy Version**: {b.strategy_version}
- **Initial Capital**: ₹{100_000:,.2f}

## Performance Summary
| Metric | In-Sample Baseline |
| :--- | :--- |
| **Total Trades** | {b.number_of_trades} |
| **Win Rate** | {b.win_rate * 100:.1f}% |
| **Profit Factor** | {b.profit_factor:.2f} |
| **Net P&L** | ₹{b.net_pnl:,.2f} |
| **Expectancy** | ₹{b.expectancy:.2f} / trade |
| **Max Drawdown** | {b.max_drawdown_pct:.2f}% |
| **Sharpe Ratio** | {b.sharpe_ratio:.2f} |
| **Max Losing Streak** | {b.max_losing_streak} trades |

## Baseline Assessment
The in-sample baseline serves as the performance benchmark against which subsequent out-of-sample and stress degradation are measured.
"""

    @staticmethod
    def generate_oos_md(report: RobustnessEvaluationReport) -> str:
        b = report.baseline
        o = report.oos
        pf_ratio = (o.profit_factor / b.profit_factor) * 100 if b.profit_factor > 0 else 0
        return f"""# Out-of-Sample Validation: VWAP-ORB

## Purpose
Determines whether strategy edge persists on unseen market data or collapses due to curve-fitting.

## Configuration & Parameters
- **Strategy Version**: {o.strategy_version}
- **Parameters**: `pullback_threshold`: 1.002, `volume_surge`: 1.5, `initial_sl_atr`: 1.5, `trailing_sl_atr`: 2.0

## Comparison Matrix
| Metric | In-Sample (IS) | Out-of-Sample (OOS) | Degradation / Delta |
| :--- | :--- | :--- | :--- |
| **Dataset Period** | {b.dataset_period} | {o.dataset_period} | - |
| **Total Trades** | {b.number_of_trades} | {o.number_of_trades} | - |
| **Win Rate** | {b.win_rate * 100:.1f}% | {o.win_rate * 100:.1f}% | {(o.win_rate - b.win_rate) * 100:+.1f}% |
| **Profit Factor** | {b.profit_factor:.2f} | {o.profit_factor:.2f} | {pf_ratio:.1f}% of IS |
| **Net P&L** | ₹{b.net_pnl:,.2f} | ₹{o.net_pnl:,.2f} | - |
| **Expectancy** | ₹{b.expectancy:.2f} / trade | ₹{o.expectancy:.2f} / trade | {o.expectancy - b.expectancy:+.2f} / trade |
| **Max Drawdown** | {b.max_drawdown_pct:.2f}% | {o.max_drawdown_pct:.2f}% | {o.max_drawdown_pct - b.max_drawdown_pct:+.2f}% |
| **Sharpe Ratio** | {b.sharpe_ratio:.2f} | {o.sharpe_ratio:.2f} | {o.sharpe_ratio - b.sharpe_ratio:+.2f} |
| **Max Losing Streak** | {b.max_losing_streak} trades | {o.max_losing_streak} trades | {o.max_losing_streak - b.max_losing_streak:+d} trades |

## OOS Verdict
- **Target Threshold**: OOS Profit Factor $\\ge 1.20$
- **Actual OOS PF**: {o.profit_factor:.2f} ({'PASSED' if o.profit_factor >= 1.20 else 'FAILED'})
"""

    @staticmethod
    def generate_walk_forward_md(report: RobustnessEvaluationReport) -> str:
        wf = report.walk_forward
        lines = [
            "# Walk-Forward Validation Report: VWAP-ORB",
            "",
            "## Summary Metrics",
            f"- **Mean Walk-Forward Efficiency (WFE)**: {wf.mean_wfe * 100:.1f}%",
            f"- **Median WFE**: {wf.median_wfe * 100:.1f}%",
            f"- **Profitable OOS Folds**: {wf.profitable_oos_folds_ratio * 100:.1f}%",
            f"- **Consistency Score**: {wf.consistency_score * 100:.1f}%",
            "",
            "## Rolling Fold Results",
            "| Fold | In-Sample Period | Out-of-Sample Period | IS PF | OOS PF | IS PnL | OOS PnL | WFE |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for f in wf.folds:
            lines.append(
                f"| {f.fold_index} | {f.in_sample_period} | {f.out_of_sample_period} | {f.is_profit_factor:.2f} | {f.oos_profit_factor:.2f} | ₹{f.is_net_pnl:,.2f} | ₹{f.oos_net_pnl:,.2f} | {f.walk_forward_efficiency * 100:.1f}% |"
            )
        return "\n".join(lines)

    @staticmethod
    def generate_parameter_sensitivity_md(report: RobustnessEvaluationReport) -> str:
        lines = [
            "# Parameter Sensitivity Analysis: VWAP-ORB",
            "",
            "## Methodology",
            "Evaluates whether small perturbations to strategy parameters cause abrupt cliff-drops in profitability.",
            "Only the approved restricted parameter ranges from the strategy specification are tested.",
            "",
            f"- **Dataset Period**: 2023-01-01 to 2024-06-30 (Full Evaluation Period)",
            f"- **Strategy Version**: {report.strategy_name}",
            "",
        ]
        for s in report.parameter_sensitivities:
            status = "STABLE" if s.is_stable else "FRAGILE / CLIFF"
            lines.extend([
                f"### Parameter: `{s.parameter_name}` (Default: `{s.default_value}`)",
                f"- **Stability Status**: **{status}**",
                f"- **Profit Factor CV**: {s.profit_factor_cv:.4f}",
                f"- **Cliff Warning**: {s.cliff_details or 'None detected'}",
                "",
                "| Value | Trades | Win Rate | Profit Factor | Expectancy | Max DD | Sharpe | Losing Streak | Net P&L | Sensitivity vs Default |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for v in s.variations:
                sumry = v.summary
                lines.append(
                    f"| {v.parameter_value} | {sumry.number_of_trades} | {sumry.win_rate*100:.1f}% | {sumry.profit_factor:.2f} | ₹{sumry.expectancy:.2f} | {sumry.max_drawdown_pct:.2f}% | {sumry.sharpe_ratio:.2f} | {sumry.max_losing_streak} | ₹{sumry.net_pnl:,.2f} | {v.neighbor_deviation_pct:+.1f}% |"
                )
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def generate_monte_carlo_md(report: RobustnessEvaluationReport) -> str:
        mc = report.monte_carlo
        return f"""# Monte Carlo Simulation Report: VWAP-ORB

## Simulation Setup
- **Iterations**: {mc.iterations:,} bootstrap permutations
- **Initial Capital**: ₹{mc.initial_capital:,.2f}

## Terminal Equity Percentiles
| Percentile | Terminal Equity | Implied Return |
| :--- | :--- | :--- |
| **99th Percentile (Optimistic Tail)** | ₹{mc.p99_terminal_equity:,.2f} | {((mc.p99_terminal_equity - mc.initial_capital)/mc.initial_capital)*100:+.1f}% |
| **75th Percentile** | ₹{mc.p75_terminal_equity:,.2f} | {((mc.p75_terminal_equity - mc.initial_capital)/mc.initial_capital)*100:+.1f}% |
| **50th Percentile (Median)** | ₹{mc.median_terminal_equity:,.2f} | {((mc.median_terminal_equity - mc.initial_capital)/mc.initial_capital)*100:+.1f}% |
| **25th Percentile** | ₹{mc.p25_terminal_equity:,.2f} | {((mc.p25_terminal_equity - mc.initial_capital)/mc.initial_capital)*100:+.1f}% |
| **5th Percentile (Adverse Tail)** | ₹{mc.p5_terminal_equity:,.2f} | {((mc.p5_terminal_equity - mc.initial_capital)/mc.initial_capital)*100:+.1f}% |

## Sequence Risk & Tail Metrics
- **Median Max Drawdown**: {mc.median_max_drawdown_pct:.2f}%
- **95th Percentile Max Drawdown**: {mc.p95_max_drawdown_pct:.2f}%
- **Worst-Case Simulation Drawdown**: {mc.worst_case_drawdown_pct:.2f}%
- **Median Losing Streak**: {mc.median_losing_streak} consecutive trades
- **95th Percentile Losing Streak**: {mc.p95_losing_streak} consecutive trades
- **Probability of Net Loss**: {mc.probability_of_loss:.1f}%
- **Risk of Ruin (> 20% DD)**: {mc.risk_of_ruin_pct:.2f}%
"""

    @staticmethod
    def generate_regime_analysis_md(report: RobustnessEvaluationReport) -> str:
        lines = [
            "# Market Regime Analysis: VWAP-ORB",
            "",
            "## Regime Performance Breakdown",
            "| Market Regime | Trades | Win Rate | Profit Factor | Expectancy | Max DD | Sharpe | Losing Streak | Net P&L |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for reg_name, sumry in report.regime_summaries.items():
            lines.append(
                f"| {reg_name} | {sumry.number_of_trades} | {sumry.win_rate*100:.1f}% | {sumry.profit_factor:.2f} | ₹{sumry.expectancy:.2f} | {sumry.max_drawdown_pct:.2f}% | {sumry.sharpe_ratio:.2f} | {sumry.max_losing_streak} | ₹{sumry.net_pnl:,.2f} |"
            )
        return "\n".join(lines)

    @staticmethod
    def generate_robustness_report_md(report: RobustnessEvaluationReport) -> str:
        lines = [
            "# Master Strategy Robustness & Overfitting Audit Report",
            f"**Strategy**: {report.strategy_name} | **Audit Date**: {report.timestamp}",
            "",
            "## Executive Verdict",
            f"# Final Recommendation: **{report.verdict.value}**",
            f"> {report.verdict_rationale}",
            "",
            "## Predefined Acceptance Scorecard",
            "| Acceptance Criterion | Status | Target Threshold | Actual Value |",
            "| :--- | :--- | :--- | :--- |",
            f"| 1. Out-of-Sample Profit Factor | {'PASS' if report.criteria_scorecard.get('1. Out-of-Sample Profit Factor >= 1.20') else 'FAIL'} | $\\ge 1.20$ | {report.oos.profit_factor:.2f} |",
            f"| 2. Walk-Forward Efficiency (WFE) | {'PASS' if report.criteria_scorecard.get('2. Walk-Forward Efficiency (WFE) >= 50%') else 'FAIL'} | $\\ge 50.0\\%$ | {report.walk_forward.mean_wfe * 100:.1f}% |",
            f"| 3. Parameter Stability (No Cliffs) | {'PASS' if report.criteria_scorecard.get('3. Parameter Stability (No Cliffs, CV <= 0.40)') else 'FAIL'} | No $>50\\%$ cliff drops | {'All Stable' if report.criteria_scorecard.get('3. Parameter Stability (No Cliffs, CV <= 0.40)') else 'Cliffs Detected'} |",
            f"| 4. Monte Carlo 95th Percentile DD | {'PASS' if report.criteria_scorecard.get('4. Monte Carlo 95th Percentile Drawdown <= 15%') else 'FAIL'} | $\\le 15.0\\%$ | {report.monte_carlo.p95_max_drawdown_pct:.2f}% |",
            f"| 5. Multi-Regime Versatility | {'PASS' if report.criteria_scorecard.get('5. Multi-Regime Profitability (>= 2 Regimes)') else 'FAIL'} | Profitable in $\\ge 2$ regimes | {sum(1 for s in report.regime_summaries.values() if s.net_pnl > 0)} profitable |",
            f"| 6. Stock Concentration Risk | {'PASS' if report.criteria_scorecard.get('6. Stock Diversification (Top Stock < 60% PnL)') else 'FAIL'} | Top stock $< 60\\%$ of PnL | {report.stress_testing.top_stock_concentration_pct:.1f}% |",
            f"| 7. Frictional Stress Survival | {'PASS' if report.criteria_scorecard.get('7. Frictional Stress Survival (+50% Costs, 2x Slippage)') else 'FAIL'} | Profitable under 1.5x fee + 2x slip | {'Positive Net PnL' if report.criteria_scorecard.get('7. Frictional Stress Survival (+50% Costs, 2x Slippage)') else 'Negative Net PnL'} |",
            "",
            "## Frictional Stress Curves",
            f"- **Cost Break-even Multiplier**: {report.stress_testing.cost_breakeven_multiplier:.2f}x standard statutory charges",
            f"- **Slippage Break-even Multiplier**: {report.stress_testing.slippage_breakeven_multiplier:.2f}x standard execution slippage",
            f"- **Top Stock P&L Concentration**: {report.stress_testing.top_stock_concentration_pct:.1f}%",
            "",
            "## Robustness Flags & Audit Warnings",
        ]
        if report.flags:
            for flag in report.flags:
                lines.append(f"- ⚠️ **{flag}**")
        else:
            lines.append("- ✅ Zero negative robustness flags raised.")

        return "\n".join(lines)

    @classmethod
    def save_reports_to_disk(cls, report: RobustnessEvaluationReport, output_dir: str = "docs/validation") -> Dict[str, str]:
        """Saves all 7 markdown artifacts to the designated documentation directory."""
        os.makedirs(output_dir, exist_ok=True)
        files = {
            "baseline.md": cls.generate_baseline_md(report),
            "oos.md": cls.generate_oos_md(report),
            "walk_forward.md": cls.generate_walk_forward_md(report),
            "parameter_sensitivity.md": cls.generate_parameter_sensitivity_md(report),
            "monte_carlo.md": cls.generate_monte_carlo_md(report),
            "regime_analysis.md": cls.generate_regime_analysis_md(report),
            "robustness_report.md": cls.generate_robustness_report_md(report),
        }

        for filename, content in files.items():
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        return files
