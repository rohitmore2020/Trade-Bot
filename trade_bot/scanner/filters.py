"""
Individual Screening Filters for the VWAP-ORB Dynamic Stock Scanner.

Each component implements a single responsibility with strict threshold checks
derived directly from the approved VWAP-ORB strategy specification.
"""

from __future__ import annotations

from typing import Optional
from trade_bot.scanner.interfaces import IScannerFilter
from trade_bot.scanner.models import FilterResult, MarketContextInput, StockMetricsInput


class FNOUniverseFilter:
    """Restricts eligible candidates strictly to NSE F&O constituents."""

    @property
    def name(self) -> str:
        return "FNO_UNIVERSE"

    def evaluate(
        self,
        stock: StockMetricsInput,
        context: Optional[MarketContextInput] = None,
    ) -> FilterResult:
        if stock.is_fno_constituent:
            return FilterResult(True, self.name, "Stock is an active F&O constituent")
        return FilterResult(False, self.name, "Stock is not in NSE F&O universe")


class LiquidityFilter:
    """Enforces minimum 30-day average daily turnover (default >= ₹100 Crore)."""

    def __init__(self, min_turnover_cr: float = 100.0) -> None:
        self.min_turnover_cr = min_turnover_cr

    @property
    def name(self) -> str:
        return "LIQUIDITY_TURNOVER"

    def evaluate(
        self,
        stock: StockMetricsInput,
        context: Optional[MarketContextInput] = None,
    ) -> FilterResult:
        if stock.avg_daily_turnover_cr >= self.min_turnover_cr:
            return FilterResult(
                True,
                self.name,
                f"Turnover ₹{stock.avg_daily_turnover_cr:.2f}Cr >= ₹{self.min_turnover_cr:.2f}Cr",
            )
        return FilterResult(
            False,
            self.name,
            f"Turnover ₹{stock.avg_daily_turnover_cr:.2f}Cr below minimum ₹{self.min_turnover_cr:.2f}Cr",
        )


class VolumeFilter:
    """Enforces minimum daily trading volume to avoid low-liquidity illiquid stocks."""

    def __init__(self, min_daily_volume: float = 100_000.0) -> None:
        self.min_daily_volume = min_daily_volume

    @property
    def name(self) -> str:
        return "MINIMUM_VOLUME"

    def evaluate(
        self,
        stock: StockMetricsInput,
        context: Optional[MarketContextInput] = None,
    ) -> FilterResult:
        if stock.avg_daily_volume >= self.min_daily_volume:
            return FilterResult(
                True,
                self.name,
                f"Daily volume {stock.avg_daily_volume:,.0f} >= {self.min_daily_volume:,.0f}",
            )
        return FilterResult(
            False,
            self.name,
            f"Daily volume {stock.avg_daily_volume:,.0f} below minimum {self.min_daily_volume:,.0f}",
        )


class VolatilityFilter:
    """Enforces 20-day ATR percentage within [1.5%, 6.0%] bounds."""

    def __init__(self, min_atr_pct: float = 1.5, max_atr_pct: float = 6.0) -> None:
        self.min_atr_pct = min_atr_pct
        self.max_atr_pct = max_atr_pct

    @property
    def name(self) -> str:
        return "VOLATILITY_ATR"

    def evaluate(
        self,
        stock: StockMetricsInput,
        context: Optional[MarketContextInput] = None,
    ) -> FilterResult:
        if self.min_atr_pct <= stock.atr_20d_pct <= self.max_atr_pct:
            return FilterResult(
                True,
                self.name,
                f"20-day ATR {stock.atr_20d_pct:.2f}% within [{self.min_atr_pct}%, {self.max_atr_pct}%]",
            )
        return FilterResult(
            False,
            self.name,
            f"20-day ATR {stock.atr_20d_pct:.2f}% outside [{self.min_atr_pct}%, {self.max_atr_pct}%]",
        )


class PriceFilter:
    """Enforces stock price within [₹200, ₹5000] bounds."""

    def __init__(self, min_price: float = 200.0, max_price: float = 5000.0) -> None:
        self.min_price = min_price
        self.max_price = max_price

    @property
    def name(self) -> str:
        return "PRICE_BAND"

    def evaluate(
        self,
        stock: StockMetricsInput,
        context: Optional[MarketContextInput] = None,
    ) -> FilterResult:
        if self.min_price <= stock.price <= self.max_price:
            return FilterResult(
                True,
                self.name,
                f"Price ₹{stock.price:.2f} within [₹{self.min_price:.2f}, ₹{self.max_price:.2f}]",
            )
        return FilterResult(
            False,
            self.name,
            f"Price ₹{stock.price:.2f} outside [₹{self.min_price:.2f}, ₹{self.max_price:.2f}]",
        )


class TradingActivityFilter:
    """Ensures stock is actively traded, not suspended/delisted, and has sufficient history."""

    def __init__(self, min_history_days: int = 20) -> None:
        self.min_history_days = min_history_days

    @property
    def name(self) -> str:
        return "TRADING_ACTIVITY"

    def evaluate(
        self,
        stock: StockMetricsInput,
        context: Optional[MarketContextInput] = None,
    ) -> FilterResult:
        if not stock.is_active:
            return FilterResult(False, self.name, "Stock is suspended or inactive")
        if stock.price <= 0 or stock.day_open <= 0 or stock.prev_day_close <= 0:
            return FilterResult(False, self.name, "Stock has invalid non-positive pricing")
        if stock.historical_bars_count < self.min_history_days:
            return FilterResult(
                False,
                self.name,
                f"Insufficient historical data: {stock.historical_bars_count} days < {self.min_history_days} required",
            )
        return FilterResult(True, self.name, "Stock is active with sufficient history")


class PreMarketFilter:
    """
    Enforces opening momentum criterion:
    Pre-market volume >= 10% of 30-day average volume OR overnight gap >= 1.0%.
    """

    def __init__(
        self,
        min_premarket_vol_pct: float = 0.10,
        min_gap_pct: float = 1.0,
    ) -> None:
        self.min_premarket_vol_pct = min_premarket_vol_pct
        self.min_gap_pct = min_gap_pct

    @property
    def name(self) -> str:
        return "PREMARKET_OR_GAP"

    def evaluate(
        self,
        stock: StockMetricsInput,
        context: Optional[MarketContextInput] = None,
    ) -> FilterResult:
        vol_passed = stock.premarket_volume_pct >= self.min_premarket_vol_pct
        gap_passed = abs(stock.overnight_gap_pct) >= self.min_gap_pct

        if vol_passed or gap_passed:
            passed_reasons = []
            if vol_passed:
                passed_reasons.append(f"Pre-market volume {stock.premarket_volume_pct * 100:.1f}% >= {self.min_premarket_vol_pct * 100:.1f}%")
            if gap_passed:
                passed_reasons.append(f"Overnight gap {stock.overnight_gap_pct:+.2f}% >= {self.min_gap_pct:.1f}%")
            return FilterResult(True, self.name, "; ".join(passed_reasons))

        return FilterResult(
            False,
            self.name,
            f"Neither pre-market volume ({stock.premarket_volume_pct * 100:.1f}% < {self.min_premarket_vol_pct * 100:.1f}%) "
            f"nor gap (|{stock.overnight_gap_pct:.2f}%| < {self.min_gap_pct:.1f}%) met threshold",
        )


class MarketRegimeFilter:
    """
    Evaluates benchmark index and India VIX conditions to ensure macro market is tradable.
    """

    def __init__(self, max_vix: float = 28.0) -> None:
        self.max_vix = max_vix

    @property
    def name(self) -> str:
        return "MARKET_REGIME"

    def evaluate(
        self,
        stock: StockMetricsInput,
        context: Optional[MarketContextInput] = None,
    ) -> FilterResult:
        if context is None:
            return FilterResult(True, self.name, "No market context provided; default allow")

        if context.india_vix > self.max_vix:
            return FilterResult(
                False,
                self.name,
                f"India VIX {context.india_vix:.2f} exceeds extreme ceiling {self.max_vix:.2f}",
            )

        if not context.vix_is_acceptable:
            return FilterResult(False, self.name, "India VIX flagged trading as unacceptable")

        return FilterResult(
            True,
            self.name,
            f"Market regime {context.nifty_regime} and VIX {context.india_vix:.2f} acceptable",
        )
