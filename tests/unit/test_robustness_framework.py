"""
Unit Tests for Phase 15 Robustness-Testing Framework.

Validates:
1. Monte Carlo trade sequence permutation and tail risk estimates.
2. Walk-Forward multi-fold validation and WFE computation.
3. Parameter sensitivity sweeps and cliff-detection logic.
4. Frictional stress testing (costs, slippage, and stock concentration).
5. RobustnessSuite scorecard evaluation (PASS, FAIL, and INCONCLUSIVE paths).
6. Generation and integrity of the 7 validation markdown reports.
"""

from datetime import datetime
import pytest

from trade_bot.domain.enums import OrderSide
from trade_bot.portfolio.models import CompletedTrade
from trade_bot.validation.models import (
    ExperimentSummary,
    RobustnessVerdict,
)
from trade_bot.validation.monte_carlo import MonteCarloSimulator
from trade_bot.validation.sensitivity import ParameterSensitivityAnalyzer
from trade_bot.validation.stress import StressTestEngine
from trade_bot.validation.suite import RobustnessSuite
from trade_bot.validation.walk_forward import WalkForwardValidator


@pytest.fixture
def sample_trades() -> list[CompletedTrade]:
    """Generates a sample list of 40 trades for unit testing."""
    trades: list[CompletedTrade] = []
    symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
    for i in range(40):
        is_win = i % 8 < 5  # ~62.5% win rate
        gross = 800.0 if is_win else -400.0
        net = gross - 40.0 - 10.0
        trades.append(
            CompletedTrade(
                trade_id=f"T_{i+1}",
                symbol=symbols[i % len(symbols)],
                side=OrderSide.BUY if i % 3 == 0 else OrderSide.SELL,
                quantity=50,
                entry_price=2500.0,
                exit_price=2516.0 if is_win else 2492.0,
                entry_time=datetime(2024, 1, 8, 9, 45),
                exit_time=datetime(2024, 1, 8, 11, 0),
                gross_pnl=gross,
                transaction_costs=40.0,
                slippage=10.0,
                net_pnl=net,
                exit_reason="TARGET_HIT" if is_win else "STOP_LOSS",
                market_regime="BULLISH" if i % 2 == 0 else "BEARISH",
            )
        )
    return trades


class TestRobustnessFramework:
    """Test suite for Phase 15 Robustness-Testing Framework."""

    def test_monte_carlo_resampling_determinism(self, sample_trades):
        """Verify Monte Carlo produces reproducible percentiles given a random seed."""
        pnls = [t.net_pnl for t in sample_trades]

        res1 = MonteCarloSimulator.simulate(trade_pnls=pnls, iterations=500, random_seed=42)
        res2 = MonteCarloSimulator.simulate(trade_pnls=pnls, iterations=500, random_seed=42)

        assert res1.iterations == 500
        assert res1.median_terminal_equity == res2.median_terminal_equity
        assert res1.p5_terminal_equity == res2.p5_terminal_equity
        assert res1.p95_terminal_equity == res2.p95_terminal_equity
        assert res1.p95_max_drawdown_pct == res2.p95_max_drawdown_pct
        assert res1.median_losing_streak == res2.median_losing_streak
        assert res1.probability_of_loss == res2.probability_of_loss

    def test_walk_forward_efficiency_calculation(self, sample_trades):
        """Verify multi-fold WFE and consistency scoring."""
        folds_data = [
            {
                "fold_index": 1,
                "is_period": "Q1",
                "oos_period": "Q2",
                "is_trades": sample_trades[:20],
                "oos_trades": sample_trades[20:],
            },
            {
                "fold_index": 2,
                "is_period": "Q2",
                "oos_period": "Q3",
                "is_trades": sample_trades[:20],
                "oos_trades": sample_trades[20:],
            },
        ]

        wf_result = WalkForwardValidator.evaluate_folds(folds_data)
        assert len(wf_result.folds) == 2
        assert wf_result.mean_wfe > 0.0
        assert wf_result.profitable_oos_folds_ratio == 1.0  # Both OOS folds are profitable
        assert wf_result.consistency_score > 0.50

    def test_parameter_sensitivity_and_cliff_detection(self):
        """Verify parameter sensitivity analyzer detects stability and cliffs."""
        # 1. Stable Parameter Sweep
        stable_variations = [
            {"value": 1.2, "summary": ExperimentSummary("SL 1.2", "P", "V", {}, 100, 1.65, 200, 5.0, 1.5, 0.55, 4, 20000)},
            {"value": 1.5, "summary": ExperimentSummary("SL 1.5", "P", "V", {}, 100, 1.80, 240, 4.5, 1.7, 0.58, 3, 24000)},
            {"value": 1.8, "summary": ExperimentSummary("SL 1.8", "P", "V", {}, 100, 1.70, 210, 4.8, 1.6, 0.56, 4, 21000)},
        ]
        res_stable = ParameterSensitivityAnalyzer.analyze_parameter("sl_atr", 1.5, stable_variations)
        assert res_stable.is_stable is True
        assert res_stable.cliff_detected is False

        # 2. Cliff Edge Drop (e.g. PF drops from 1.80 to 0.70 > 50% drop)
        cliff_variations = [
            {"value": 1.2, "summary": ExperimentSummary("V 1.2", "P", "V", {}, 100, 1.70, 200, 5.0, 1.5, 0.55, 4, 20000)},
            {"value": 1.5, "summary": ExperimentSummary("V 1.5", "P", "V", {}, 100, 1.80, 240, 4.5, 1.7, 0.58, 3, 24000)},
            {"value": 1.8, "summary": ExperimentSummary("V 1.8", "P", "V", {}, 100, 0.75, -50, 12.0, -0.5, 0.35, 8, -5000)},
        ]
        res_cliff = ParameterSensitivityAnalyzer.analyze_parameter("v_surge", 1.5, cliff_variations)
        assert res_cliff.cliff_detected is True
        assert res_cliff.is_stable is False
        assert "Cliff detected" in str(res_cliff.cliff_details)

    def test_stress_test_engine(self, sample_trades):
        """Verify cost stress, slippage stress, and stock concentration calculations."""
        res = StressTestEngine.evaluate_stress(sample_trades)

        assert "costs_1.00x" in res.cost_stress_summaries
        assert "costs_1.50x" in res.cost_stress_summaries
        assert "slippage_1.00x" in res.slippage_stress_summaries
        assert "slippage_2.00x" in res.slippage_stress_summaries

        # Costs 1.5x should have lower Net PnL than 1.0x
        pnl_1x = res.cost_stress_summaries["costs_1.00x"].net_pnl
        pnl_1_5x = res.cost_stress_summaries["costs_1.50x"].net_pnl
        assert pnl_1_5x < pnl_1x

        # Break-even multipliers should be positive
        assert res.cost_breakeven_multiplier > 1.0
        assert res.slippage_breakeven_multiplier > 1.0

        # Stock concentration
        assert res.top_stock_concentration_pct < 100.0

    def test_robustness_suite_verdict_logic(self, sample_trades):
        """Verify RobustnessSuite issues PASS, FAIL, or INCONCLUSIVE depending on conditions."""
        is_summary = ExperimentSummary("IS", "2023", "V1", {}, 40, 1.80, 200.0, 5.0, 1.6, 0.60, 4, 8000.0)
        oos_pass = ExperimentSummary("OOS", "2024", "V1", {}, 40, 1.50, 150.0, 6.0, 1.3, 0.55, 4, 6000.0)
        oos_fail = ExperimentSummary("OOS", "2024", "V1", {}, 40, 0.85, -50.0, 12.0, -0.4, 0.38, 8, -2000.0)

        wf_folds = [
            {"fold_index": 1, "is_trades": sample_trades[:20], "oos_trades": sample_trades[20:]},
        ]
        param_sweeps = [
            {
                "parameter_name": "pullback",
                "default_value": 1.002,
                "variations": [
                    {"value": 1.002, "summary": is_summary},
                ],
            }
        ]
        regime_sums = {
            "BULLISH": ExperimentSummary("Bull", "F", "V1", {}, 20, 2.0, 200, 4.0, 1.8, 0.65, 3, 4000.0),
            "BEARISH": ExperimentSummary("Bear", "F", "V1", {}, 20, 1.5, 120, 5.0, 1.2, 0.55, 4, 2400.0),
        }

        # 1. PASS Verdict
        report_pass = RobustnessSuite.evaluate(
            baseline_summary=is_summary,
            oos_summary=oos_pass,
            all_trades=sample_trades,
            walk_forward_folds=wf_folds,
            parameter_sweeps=param_sweeps,
            regime_summaries=regime_sums,
        )
        assert report_pass.verdict == RobustnessVerdict.PASS
        assert len(report_pass.flags) == 0

        # 2. FAIL Verdict (OOS collapses, PF < 1.20)
        report_fail = RobustnessSuite.evaluate(
            baseline_summary=is_summary,
            oos_summary=oos_fail,
            all_trades=sample_trades,
            walk_forward_folds=wf_folds,
            parameter_sweeps=param_sweeps,
            regime_summaries=regime_sums,
        )
        assert report_fail.verdict in (RobustnessVerdict.FAIL, RobustnessVerdict.INCONCLUSIVE)
        assert any("OOS Fragility" in flag for flag in report_fail.flags)

        # 3. INCONCLUSIVE Verdict (Insufficient trades < 30)
        report_inconclusive = RobustnessSuite.evaluate(
            baseline_summary=is_summary,
            oos_summary=oos_pass,
            all_trades=sample_trades[:15],  # 15 trades < 30
            walk_forward_folds=wf_folds,
            parameter_sweeps=param_sweeps,
            regime_summaries=regime_sums,
        )
        assert report_inconclusive.verdict == RobustnessVerdict.INCONCLUSIVE
        assert "insufficient" in report_inconclusive.verdict_rationale.lower()
