"""
Unit and Integration Tests for Dynamic Stock Scanner (Phase 7).

Covers all required specifications:
1. Candidate passes all filters
2. Candidate fails Liquidity filter (< ₹100 Cr)
3. Candidate fails Volume filter (< 100k shares)
4. Candidate fails Volatility/ATR filter (< 1.5% or > 6.0%)
5. Candidate fails Price filter (< ₹200 or > ₹5000)
6. Insufficient trading history (< 20 days)
7. Inactive / suspended stock
8. Pre-market rejection (vol < 10% AND gap < 1.0%)
9. Gap-based acceptance (vol < 10% BUT gap >= 1.0%)
10. Pre-market vol-based acceptance (gap < 1.0% BUT vol >= 10%)
11. Market regime / VIX rejection (> 28.0)
12. Exact boundary values (Turnover 100.0, Price 200/5000, ATR 1.5/6.0)
13. Empty universe handling
14. Malformed market data handling
15. Complete pipeline integration test (ranking and max candidates slice)
16. Architectural purity audit (zero Upstox/broker imports)
"""

from dataclasses import replace
from datetime import date, datetime, timezone
import pytest
from trade_bot.domain.enums import MarketRegime
from trade_bot.scanner.filters import (
    FNOUniverseFilter,
    LiquidityFilter,
    MarketRegimeFilter,
    PreMarketFilter,
    PriceFilter,
    TradingActivityFilter,
    VolatilityFilter,
    VolumeFilter,
)
from trade_bot.scanner.models import (
    MarketContextInput,
    StockMetricsInput,
)
from trade_bot.scanner.providers import HistoricalUniverseProvider, StaticUniverseProvider
from trade_bot.scanner.scanner import CandidateScanner


@pytest.fixture
def baseline_valid_stock() -> StockMetricsInput:
    return StockMetricsInput(
        symbol="RELIANCE",
        instrument_id="NSE_EQ|INE002A01018",
        price=2500.0,
        avg_daily_turnover_cr=500.0,  # >= 100 Cr
        avg_daily_volume=2_000_000.0,  # >= 100k
        atr_20d=60.0,
        atr_20d_pct=2.4,  # in [1.5%, 6.0%]
        prev_day_close=2480.0,
        day_open=2510.0,
        overnight_gap_pct=1.21,  # >= 1.0%
        premarket_volume=250_000,
        premarket_volume_pct=0.125,  # >= 10%
        is_fno_constituent=True,
        is_active=True,
        historical_bars_count=30,  # >= 20
    )


@pytest.fixture
def baseline_market_context() -> MarketContextInput:
    return MarketContextInput(
        nifty_price=21550.0,
        nifty_vwap=21500.0,
        nifty_regime=MarketRegime.BULLISH,
        india_vix=14.5,
        vix_is_acceptable=True,
    )


@pytest.fixture
def scanner() -> CandidateScanner:
    return CandidateScanner(min_candidates=10, max_candidates=30)


# ==============================================================================
# 1. Candidate Passes All Filters
# ==============================================================================

def test_stock_passes_all_filters(
    scanner: CandidateScanner,
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    results = scanner.scan([baseline_valid_stock], baseline_market_context)
    assert len(results) == 1
    cand = results[0]
    assert cand.symbol == "RELIANCE"
    assert cand.is_eligible is True
    assert cand.rank == 1
    assert "Passed all filters" in cand.status_reason


# ==============================================================================
# 2. Candidate Fails Liquidity Filter (< ₹100 Cr)
# ==============================================================================

def test_stock_fails_liquidity(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    stock_low_liq = replace(baseline_valid_stock, avg_daily_turnover_cr=75.0)  # < 100 Cr
    flt = LiquidityFilter(min_turnover_cr=100.0)
    res = flt.evaluate(stock_low_liq, baseline_market_context)
    assert res.passed is False
    assert "below minimum ₹100.00Cr" in res.reason


# ==============================================================================
# 3. Candidate Fails Volume Filter (< 100k shares)
# ==============================================================================

def test_stock_fails_volume(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    stock_low_vol = replace(baseline_valid_stock, avg_daily_volume=50_000.0)  # < 100k
    flt = VolumeFilter(min_daily_volume=100_000.0)
    res = flt.evaluate(stock_low_vol, baseline_market_context)
    assert res.passed is False
    assert "below minimum 100,000" in res.reason


# ==============================================================================
# 4. Candidate Fails ATR Filter (< 1.5% or > 6.0%)
# ==============================================================================

def test_stock_fails_atr(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    flt = VolatilityFilter(min_atr_pct=1.5, max_atr_pct=6.0)

    # Low ATR: 1.1% < 1.5%
    stock_low_atr = replace(baseline_valid_stock, atr_20d_pct=1.1)
    res_low = flt.evaluate(stock_low_atr, baseline_market_context)
    assert res_low.passed is False

    # High ATR: 7.2% > 6.0%
    stock_high_atr = replace(baseline_valid_stock, atr_20d_pct=7.2)
    res_high = flt.evaluate(stock_high_atr, baseline_market_context)
    assert res_high.passed is False


# ==============================================================================
# 5. Candidate Fails Price Filter (< ₹200 or > ₹5000)
# ==============================================================================

def test_stock_fails_price(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    flt = PriceFilter(min_price=200.0, max_price=5000.0)

    # Penny/low stock: ₹150 < ₹200
    stock_penny = replace(baseline_valid_stock, price=150.0)
    res_low = flt.evaluate(stock_penny, baseline_market_context)
    assert res_low.passed is False

    # High price stock: ₹6000 > ₹5000
    stock_expensive = replace(baseline_valid_stock, price=6000.0)
    res_high = flt.evaluate(stock_expensive, baseline_market_context)
    assert res_high.passed is False


# ==============================================================================
# 6. Insufficient Trading History (< 20 days)
# ==============================================================================

def test_insufficient_trading_history(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    stock_new_listing = replace(baseline_valid_stock, historical_bars_count=12)  # < 20
    flt = TradingActivityFilter(min_history_days=20)
    res = flt.evaluate(stock_new_listing, baseline_market_context)
    assert res.passed is False
    assert "Insufficient historical data" in res.reason


# ==============================================================================
# 7. Inactive / Suspended Stock
# ==============================================================================

def test_inactive_stock(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    stock_suspended = replace(baseline_valid_stock, is_active=False)
    flt = TradingActivityFilter()
    res = flt.evaluate(stock_suspended, baseline_market_context)
    assert res.passed is False
    assert "suspended or inactive" in res.reason


# ==============================================================================
# 8. Pre-Market Rejection (Vol < 10% AND Gap < 1.0%)
# ==============================================================================

def test_premarket_rejection(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    # Both fail: Pre-market volume 4% (< 10%) and Gap 0.3% (< 1.0%)
    stock_quiet = replace(baseline_valid_stock, premarket_volume_pct=0.04, overnight_gap_pct=0.3)
    flt = PreMarketFilter(min_premarket_vol_pct=0.10, min_gap_pct=1.0)
    res = flt.evaluate(stock_quiet, baseline_market_context)
    assert res.passed is False


# ==============================================================================
# 9. Gap-Based Acceptance (Vol < 10% BUT Gap >= 1.0%)
# ==============================================================================

def test_gap_based_acceptance(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    # Pre-market volume is only 3% (< 10%), BUT overnight gap is +1.8% (>= 1.0%)
    stock_gap_only = replace(baseline_valid_stock, premarket_volume_pct=0.03, overnight_gap_pct=1.8)
    flt = PreMarketFilter(min_premarket_vol_pct=0.10, min_gap_pct=1.0)
    res = flt.evaluate(stock_gap_only, baseline_market_context)
    assert res.passed is True
    assert "Overnight gap" in res.reason


# ==============================================================================
# 10. Pre-market Vol-Based Acceptance (Gap < 1.0% BUT Vol >= 10%)
# ==============================================================================

def test_premarket_vol_acceptance(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    # Overnight gap is 0.2% (< 1.0%), BUT pre-market volume is 15% (>= 10%)
    stock_vol_only = replace(baseline_valid_stock, premarket_volume_pct=0.15, overnight_gap_pct=0.2)
    flt = PreMarketFilter(min_premarket_vol_pct=0.10, min_gap_pct=1.0)
    res = flt.evaluate(stock_vol_only, baseline_market_context)
    assert res.passed is True
    assert "Pre-market volume" in res.reason


# ==============================================================================
# 11. Market Regime & India VIX Rejection (> 28.0)
# ==============================================================================

def test_vix_rejection(
    baseline_valid_stock: StockMetricsInput,
) -> None:
    flt = MarketRegimeFilter(max_vix=28.0)

    # Extreme volatility day: VIX = 32.5 > 28.0
    context_panic = MarketContextInput(
        nifty_price=20000.0,
        nifty_vwap=20500.0,
        nifty_regime=MarketRegime.BEARISH,
        india_vix=32.5,
        vix_is_acceptable=False,
    )
    res = flt.evaluate(baseline_valid_stock, context_panic)
    assert res.passed is False
    assert "exceeds extreme ceiling" in res.reason


# ==============================================================================
# 12. Exact Boundary Values
# ==============================================================================

def test_exact_boundary_values(
    baseline_market_context: MarketContextInput,
) -> None:
    # Exactly on lower/upper limits: Turnover=100.0, ATR%=1.5, Price=200.0
    stock_lower = StockMetricsInput(
        symbol="BOUNDARY_LOW",
        instrument_id="NSE_EQ|BOUNDARY_LOW",
        price=200.0,  # Exact lower limit
        avg_daily_turnover_cr=100.0,  # Exact lower limit
        avg_daily_volume=100_000.0,  # Exact lower limit
        atr_20d=3.0,
        atr_20d_pct=1.5,  # Exact lower limit
        prev_day_close=198.0,
        day_open=200.0,
        overnight_gap_pct=1.01,
        premarket_volume=10_000,
        premarket_volume_pct=0.10,  # Exact lower limit
        is_fno_constituent=True,
        is_active=True,
        historical_bars_count=20,  # Exact lower limit
    )
    scanner = CandidateScanner()
    res_lower = scanner.scan([stock_lower], baseline_market_context)
    assert len(res_lower) == 1
    assert res_lower[0].is_eligible is True

    # Exact upper limits: Price=5000.0, ATR%=6.0
    stock_upper = StockMetricsInput(
        symbol="BOUNDARY_HIGH",
        instrument_id="NSE_EQ|BOUNDARY_HIGH",
        price=5000.0,  # Exact upper limit
        avg_daily_turnover_cr=200.0,
        avg_daily_volume=200_000.0,
        atr_20d=300.0,
        atr_20d_pct=6.0,  # Exact upper limit
        prev_day_close=4950.0,
        day_open=5000.0,
        overnight_gap_pct=1.01,
        premarket_volume=20_000,
        premarket_volume_pct=0.10,
        is_fno_constituent=True,
        is_active=True,
        historical_bars_count=25,
    )
    res_upper = scanner.scan([stock_upper], baseline_market_context)
    assert len(res_upper) == 1
    assert res_upper[0].is_eligible is True


# ==============================================================================
# 13. Empty Universe Handling
# ==============================================================================

def test_empty_universe_handling(
    scanner: CandidateScanner,
    baseline_market_context: MarketContextInput,
) -> None:
    res = scanner.scan([], baseline_market_context)
    assert res == []


# ==============================================================================
# 14. Malformed Market Data Handling
# ==============================================================================

def test_malformed_market_data_handling(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    # Zero or negative pricing
    stock_zero_price = replace(baseline_valid_stock, price=0.0)
    flt = TradingActivityFilter()
    res = flt.evaluate(stock_zero_price, baseline_market_context)
    assert res.passed is False
    assert "invalid non-positive pricing" in res.reason


# ==============================================================================
# 15. Complete Pipeline Integration Test (Ranking & Candidate Slicing)
# ==============================================================================

def test_complete_pipeline_ranking_and_slicing(
    baseline_valid_stock: StockMetricsInput,
    baseline_market_context: MarketContextInput,
) -> None:
    scanner = CandidateScanner(min_candidates=2, max_candidates=3)

    stocks = []
    # Create 5 stocks with varying turnover
    for i in range(1, 6):
        stocks.append(
            StockMetricsInput(
                symbol=f"STOCK_{i}",
                instrument_id=f"NSE_EQ|STOCK_{i}",
                price=1000.0,
                avg_daily_turnover_cr=100.0 * i,  # 100, 200, 300, 400, 500 Cr
                avg_daily_volume=200_000.0,
                atr_20d=25.0,
                atr_20d_pct=2.5,
                prev_day_close=990.0,
                day_open=1005.0,
                overnight_gap_pct=1.5,
                premarket_volume=25_000,
                premarket_volume_pct=0.125,
                is_fno_constituent=True,
                is_active=True,
                historical_bars_count=30,
            )
        )

    scan_ts = datetime(2024, 1, 10, 9, 10, tzinfo=timezone.utc)
    results = scanner.scan(stocks, baseline_market_context, scan_timestamp=scan_ts)

    # Max candidates is 3, so only top 3 should be returned
    assert len(results) == 3
    # Sorted by turnover/score descending: STOCK_5 (500 Cr), STOCK_4 (400 Cr), STOCK_3 (300 Cr)
    assert results[0].symbol == "STOCK_5"
    assert results[0].rank == 1
    assert results[1].symbol == "STOCK_4"
    assert results[1].rank == 2
    assert results[2].symbol == "STOCK_3"
    assert results[2].rank == 3
    assert results[0].scan_timestamp == scan_ts


# ==============================================================================
# 16. Pure Business Logic & Zero Infrastructure Imports Audit
# ==============================================================================

def test_scanner_purity_zero_infrastructure_imports() -> None:
    import sys
    forbidden_tokens = ["upstox", "websocket", "requests", "httpx", "sqlalchemy"]
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("trade_bot.scanner"):
            module = sys.modules[mod_name]
            module_file = getattr(module, "__file__", "")
            if module_file:
                with open(module_file, "r", encoding="utf-8") as f:
                    content = f.read().lower()
                    for token in forbidden_tokens:
                        assert f"import {token}" not in content, f"Forbidden '{token}' in {module_file}"
                        assert f"from {token}" not in content, f"Forbidden '{token}' in {module_file}"


def test_universe_providers() -> None:
    static_prov = StaticUniverseProvider(["RELIANCE", "TCS"])
    assert static_prov.get_fno_universe(date(2024, 1, 15)) == ["RELIANCE", "TCS"]

    hist_prov = HistoricalUniverseProvider()
    univ = hist_prov.get_fno_universe(date(2024, 1, 15))
    assert "RELIANCE" in univ
    assert "INFY" in univ
