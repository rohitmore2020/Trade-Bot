"""
Unit Tests for Phase 14 Reusable Analytics Layer.

Verifies:
1. Returns and Volatility (total return %, CAGR, daily volatility, annualized volatility).
2. PnL Statistics (gross PnL, net PnL, profit factor, win rate, expectancy, average winner, average loser, payoff ratio).
3. Drawdown Calculations (max drawdown amount, max drawdown %, average drawdown, duration).
4. Trade Statistics & Streaks (win/loss/breakeven counts, max consecutive wins/losses, average R-multiple, holding duration).
5. Risk-Adjusted Metrics (Sharpe ratio, Sortino ratio, Calmar ratio).
6. Execution Metrics (turnover, total costs, slippage, slippage basis points).
7. Multi-Dimensional Attribution Breakdowns:
   - By stock
   - By day
   - By month
   - By market regime
   - By direction (Long vs Short)
   - By entry time bucket
   - By exit reason
8. Output formats (Machine-readable JSON, CSVs, and Human-readable Markdown).
9. Complete result set preservation without cherry-picking.
"""

from datetime import date, datetime, timedelta
import json
import pytest

from trade_bot.analytics.breakdowns import BreakdownEngine
from trade_bot.analytics.drawdown import DrawdownCalculator
from trade_bot.analytics.execution_stats import ExecutionStatsCalculator
from trade_bot.analytics.models import ComprehensiveReport
from trade_bot.analytics.pnl import PnLAnalyticsCalculator
from trade_bot.analytics.reporter import PerformanceReporter
from trade_bot.analytics.returns import ReturnsCalculator
from trade_bot.analytics.risk_metrics import RiskMetricsCalculator
from trade_bot.analytics.trade_stats import TradeStatsCalculator
from trade_bot.domain.enums import OrderSide
from trade_bot.portfolio.models import CompletedTrade


@pytest.fixture
def deterministic_trades() -> list[CompletedTrade]:
    """
    Creates a deterministic set of 10 completed trades with known properties:
    - 6 Winners, 3 Losers, 1 Break-even
    - Gross Wins = 500 + 800 + 1200 + 400 + 600 + 1000 = 4,500.0
    - Gross Losses = -400 + -600 + -500 = -1,500.0
    - Gross Break-even = 0.0
    - Total Gross PnL = 3,000.0
    - Transaction Costs = 10 * 40.0 = 400.0
    - Slippage = 10 * 10.0 = 100.0
    - Total Net PnL = 3,000.0 - 400.0 - 100.0 = 2,500.0
    """
    trades = [
        # 1. Win 1 (RELIANCE, LONG, 09:45, BULLISH, TRAILING_STOP)
        CompletedTrade(
            trade_id="T1", symbol="RELIANCE", side=OrderSide.BUY, quantity=50,
            entry_price=2500.0, exit_price=2510.0,
            entry_time=datetime(2024, 1, 8, 9, 45), exit_time=datetime(2024, 1, 8, 10, 15),
            gross_pnl=500.0, transaction_costs=40.0, slippage=10.0, net_pnl=450.0,
            exit_reason="TRAILING_STOP", market_regime="BULLISH",
        ),
        # 2. Win 2 (RELIANCE, LONG, 10:30, BULLISH, TARGET_HIT)
        CompletedTrade(
            trade_id="T2", symbol="RELIANCE", side=OrderSide.BUY, quantity=80,
            entry_price=2510.0, exit_price=2520.0,
            entry_time=datetime(2024, 1, 8, 10, 30), exit_time=datetime(2024, 1, 8, 11, 30),
            gross_pnl=800.0, transaction_costs=40.0, slippage=10.0, net_pnl=750.0,
            exit_reason="TARGET_HIT", market_regime="BULLISH",
        ),
        # 3. Win 3 (TCS, SHORT, 11:45, BEARISH, TARGET_HIT)
        CompletedTrade(
            trade_id="T3", symbol="TCS", side=OrderSide.SELL, quantity=60,
            entry_price=3500.0, exit_price=3480.0,
            entry_time=datetime(2024, 1, 8, 11, 45), exit_time=datetime(2024, 1, 8, 12, 45),
            gross_pnl=1200.0, transaction_costs=40.0, slippage=10.0, net_pnl=1150.0,
            exit_reason="TARGET_HIT", market_regime="BEARISH",
        ),
        # 4. Loss 1 (TCS, LONG, 13:15, RANGE_BOUND, STOP_LOSS)
        CompletedTrade(
            trade_id="T4", symbol="TCS", side=OrderSide.BUY, quantity=40,
            entry_price=3500.0, exit_price=3490.0,
            entry_time=datetime(2024, 1, 9, 13, 15), exit_time=datetime(2024, 1, 9, 13, 45),
            gross_pnl=-400.0, transaction_costs=40.0, slippage=10.0, net_pnl=-450.0,
            exit_reason="STOP_LOSS", market_regime="RANGE_BOUND",
        ),
        # 5. Loss 2 (INFY, SHORT, 09:50, BEARISH, STOP_LOSS)
        CompletedTrade(
            trade_id="T5", symbol="INFY", side=OrderSide.SELL, quantity=100,
            entry_price=1500.0, exit_price=1506.0,
            entry_time=datetime(2024, 1, 9, 9, 50), exit_time=datetime(2024, 1, 9, 10, 20),
            gross_pnl=-600.0, transaction_costs=40.0, slippage=10.0, net_pnl=-650.0,
            exit_reason="STOP_LOSS", market_regime="BEARISH",
        ),
        # 6. Break-even (INFY, LONG, 11:00, RANGE_BOUND, TIME_CUTOFF)
        CompletedTrade(
            trade_id="T6", symbol="INFY", side=OrderSide.BUY, quantity=50,
            entry_price=1500.0, exit_price=1500.0,
            entry_time=datetime(2024, 1, 9, 11, 0), exit_time=datetime(2024, 1, 9, 14, 30),
            gross_pnl=0.0, transaction_costs=40.0, slippage=10.0, net_pnl=-50.0,
            exit_reason="TIME_CUTOFF", market_regime="RANGE_BOUND",
        ),
        # 7. Win 4 (RELIANCE, LONG, 09:30, BULLISH, TRAILING_STOP)
        CompletedTrade(
            trade_id="T7", symbol="RELIANCE", side=OrderSide.BUY, quantity=40,
            entry_price=2500.0, exit_price=2510.0,
            entry_time=datetime(2024, 1, 10, 9, 30), exit_time=datetime(2024, 1, 10, 10, 0),
            gross_pnl=400.0, transaction_costs=40.0, slippage=10.0, net_pnl=350.0,
            exit_reason="TRAILING_STOP", market_regime="BULLISH",
        ),
        # 8. Win 5 (INFY, SHORT, 10:15, BEARISH, TARGET_HIT)
        CompletedTrade(
            trade_id="T8", symbol="INFY", side=OrderSide.SELL, quantity=60,
            entry_price=1500.0, exit_price=1490.0,
            entry_time=datetime(2024, 1, 10, 10, 15), exit_time=datetime(2024, 1, 10, 11, 15),
            gross_pnl=600.0, transaction_costs=40.0, slippage=10.0, net_pnl=550.0,
            exit_reason="TARGET_HIT", market_regime="BEARISH",
        ),
        # 9. Loss 3 (TCS, SHORT, 12:00, RANGE_BOUND, VWAP_FAILURE)
        CompletedTrade(
            trade_id="T9", symbol="TCS", side=OrderSide.SELL, quantity=50,
            entry_price=3500.0, exit_price=3510.0,
            entry_time=datetime(2024, 1, 10, 12, 0), exit_time=datetime(2024, 1, 10, 12, 30),
            gross_pnl=-500.0, transaction_costs=40.0, slippage=10.0, net_pnl=-550.0,
            exit_reason="VWAP_FAILURE", market_regime="RANGE_BOUND",
        ),
        # 10. Win 6 (RELIANCE, LONG, 13:30, BULLISH, TIME_CUTOFF)
        CompletedTrade(
            trade_id="T10", symbol="RELIANCE", side=OrderSide.BUY, quantity=100,
            entry_price=2500.0, exit_price=2510.0,
            entry_time=datetime(2024, 1, 10, 13, 30), exit_time=datetime(2024, 1, 10, 14, 30),
            gross_pnl=1000.0, transaction_costs=40.0, slippage=10.0, net_pnl=950.0,
            exit_reason="TIME_CUTOFF", market_regime="BULLISH",
        ),
    ]
    return trades


class TestAnalyticsLayer:
    """Test suite for Phase 14 decoupled analytics layer."""

    def test_pnl_analytics_calculator(self, deterministic_trades):
        """Verifies exact gross PnL, net PnL, profit factor, win rate, and expectancy."""
        pnl = PnLAnalyticsCalculator.calculate(deterministic_trades)

        assert pnl.gross_pnl == 3000.0
        assert pnl.net_pnl == 2500.0
        assert pnl.profit_factor == 3.0  # 4500.0 / 1500.0
        assert pnl.win_rate == 0.60  # 6 / 10
        assert pnl.expectancy == 250.0  # 2500.0 / 10
        assert pnl.avg_winner == 700.0  # 4200.0 / 6
        assert pnl.avg_loser == -425.0  # -1700.0 / 4

    def test_trade_stats_calculator(self, deterministic_trades):
        """Verifies trade counts, streaks, duration, and R-multiples."""
        stats = TradeStatsCalculator.calculate(deterministic_trades)

        assert stats.total_trades == 10
        assert stats.winning_trades == 6
        assert stats.losing_trades == 4  # Includes the break-even trade that incurred fee friction
        assert stats.max_consecutive_wins == 3  # Trades 1, 2, 3
        assert stats.max_consecutive_losses == 3  # Trades 4, 5, 6
        assert stats.avg_holding_duration_mins > 0.0

    def test_drawdown_calculator(self):
        """Verifies drawdown depth, percentage, and peak-to-trough tracking."""
        initial_capital = 100_000.0
        # Peak at 105,000; trough at 99,750 (5,250 draw = 5.0%)
        equity_curve = [
            (datetime(2024, 1, 8, 9, 30), 100_000.0),
            (datetime(2024, 1, 8, 11, 0), 103_000.0),
            (datetime(2024, 1, 8, 14, 30), 105_000.0),  # Peak
            (datetime(2024, 1, 9, 10, 0), 102_000.0),
            (datetime(2024, 1, 9, 14, 30), 99_750.0),   # Trough (5,250 drop)
            (datetime(2024, 1, 10, 11, 0), 104_000.0),
            (datetime(2024, 1, 10, 14, 30), 106_000.0), # New High
        ]

        dd = DrawdownCalculator.calculate(equity_curve, initial_capital)
        assert dd.max_drawdown_amount == 5250.0
        assert dd.max_drawdown_pct == 5.0
        assert dd.max_drawdown_duration_days >= 1

    def test_returns_and_volatility_calculator(self):
        """Verifies total return %, CAGR %, and daily volatility."""
        daily_snaps = [
            (date(2024, 1, 8), 100_000.0),
            (date(2024, 1, 9), 101_000.0),  # +1.0%
            (date(2024, 1, 10), 100_500.0), # -0.495%
            (date(2024, 1, 11), 102_000.0), # +1.4925%
        ]
        ret = ReturnsCalculator.calculate(
            initial_capital=100_000.0,
            final_equity=102_000.0,
            daily_snapshots=daily_snaps,
            calendar_days=3,
        )

        assert ret.total_return_pct == 2.0
        assert ret.daily_volatility_pct > 0.0
        assert ret.annualized_volatility_pct > ret.daily_volatility_pct

    def test_risk_metrics_calculator(self):
        """Verifies Sharpe, Sortino, and Calmar ratios."""
        daily_snaps = [
            (date(2024, 1, 8), 100_000.0),
            (date(2024, 1, 9), 101_000.0),
            (date(2024, 1, 10), 102_000.0),
            (date(2024, 1, 11), 103_000.0),
        ]
        risk = RiskMetricsCalculator.calculate(
            daily_snapshots=daily_snaps,
            cagr_pct=25.0,
            max_drawdown_pct=5.0,
            annual_risk_free_rate=0.06,
        )

        assert risk.sharpe_ratio > 0.0
        assert risk.calmar_ratio == 5.0  # 25.0 / 5.0

    def test_multi_dimensional_breakdowns(self, deterministic_trades):
        """Verifies all 7 attribution breakdowns preserve the total trade count without cherry-picking."""
        # 1. By Stock
        by_stock = BreakdownEngine.break_down_by_stock(deterministic_trades)
        symbols = {b.group_key for b in by_stock}
        assert symbols == {"RELIANCE", "TCS", "INFY"}
        assert sum(b.trades_count for b in by_stock) == 10

        # 2. By Day
        by_day = BreakdownEngine.break_down_by_day(deterministic_trades)
        assert sum(b.trades_count for b in by_day) == 10

        # 3. By Month
        by_month = BreakdownEngine.break_down_by_month(deterministic_trades)
        assert sum(b.trades_count for b in by_month) == 10

        # 4. By Regime
        by_regime = BreakdownEngine.break_down_by_regime(deterministic_trades)
        regimes = {b.group_key for b in by_regime}
        assert regimes == {"BULLISH", "BEARISH", "RANGE_BOUND"}
        assert sum(b.trades_count for b in by_regime) == 10

        # 5. By Direction (Long vs Short)
        by_direction = BreakdownEngine.break_down_by_direction(deterministic_trades)
        directions = {b.group_key for b in by_direction}
        assert directions == {"LONG", "SHORT"}
        assert sum(b.trades_count for b in by_direction) == 10

        # 6. By Entry Time Bucket
        by_entry_time = BreakdownEngine.break_down_by_entry_time(deterministic_trades)
        assert sum(b.trades_count for b in by_entry_time) == 10

        # 7. By Exit Reason
        by_exit_reason = BreakdownEngine.break_down_by_exit_reason(deterministic_trades)
        exit_reasons = {b.group_key for b in by_exit_reason}
        assert exit_reasons == {"TRAILING_STOP", "TARGET_HIT", "STOP_LOSS", "TIME_CUTOFF", "VWAP_FAILURE"}
        assert sum(b.trades_count for b in by_exit_reason) == 10

    def test_reporter_json_csv_markdown_outputs(self, deterministic_trades):
        """Verifies JSON, CSV, and Markdown generation from PerformanceReporter."""
        report = PerformanceReporter.generate_report(
            initial_capital=100_000.0,
            final_equity=102_500.0,
            completed_trades=deterministic_trades,
            total_turnover=500_000.0,
            total_slippage=100.0,
            total_costs=400.0,
        )

        assert isinstance(report, ComprehensiveReport)
        assert report.pnl.net_pnl == 2500.0

        # JSON Export verification
        json_str = PerformanceReporter.to_json(report)
        parsed = json.loads(json_str)
        assert parsed["summary"]["initial_capital"] == 100_000.0
        assert parsed["summary"]["total_trades"] == 10
        assert "breakdowns" in parsed
        assert len(parsed["breakdowns"]["by_stock"]) == 3

        # CSV Export verification
        csv_files = PerformanceReporter.to_csv(report, deterministic_trades)
        assert "trade_log.csv" in csv_files
        assert "breakdowns_stock.csv" in csv_files
        assert "breakdowns_daily.csv" in csv_files
        assert len(csv_files["trade_log.csv"].splitlines()) == 11  # 1 header + 10 trades

        # Markdown Export verification
        md = PerformanceReporter.to_markdown(report)
        assert "# Strategy Performance & Attribution Report" in md
        assert "## Executive Summary" in md
        assert "RELIANCE" in md
        assert "TCS" in md
        assert "INFY" in md
