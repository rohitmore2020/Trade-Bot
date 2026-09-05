"""
Candidate Scanner for VWAP-ORB Strategy.

Orchestrates sequential execution of screening filters, ranks eligible candidates,
and returns strongly typed ScannedCandidate objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
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
from trade_bot.scanner.interfaces import ICandidateScanner, IScannerFilter
from trade_bot.scanner.models import (
    MarketContextInput,
    ScannedCandidate,
    StockMetricsInput,
)


class CandidateScanner:
    """
    Dynamic stock scanner implementing the exact multi-stage VWAP-ORB pipeline:
    1. F&O Universe Filter
    2. Liquidity Filter (Turnover >= ₹100 Cr)
    3. Volume Filter (Daily Volume >= 100k)
    4. Volatility Filter (20-day ATR% in [1.5%, 6.0%])
    5. Price Filter (Price in [₹200, ₹5000])
    6. Trading Activity Filter (Active, valid prices, >= 20 days history)
    7. Pre-Market Activity / Gap Filter (Pre-market vol >= 10% OR gap >= 1.0%)
    8. Market Regime Eligibility (VIX <= 28.0)
    9. Deterministic Candidate Ranking & Selection (Top 10-30 candidates)
    """

    def __init__(
        self,
        min_candidates: int = 10,
        max_candidates: int = 30,
        filters: Optional[List[IScannerFilter]] = None,
    ) -> None:
        self.min_candidates = min_candidates
        self.max_candidates = max_candidates

        # Default standard pipeline in exact logical order
        self.filters: List[IScannerFilter] = filters or [
            FNOUniverseFilter(),
            LiquidityFilter(min_turnover_cr=100.0),
            VolumeFilter(min_daily_volume=100_000.0),
            VolatilityFilter(min_atr_pct=1.5, max_atr_pct=6.0),
            PriceFilter(min_price=200.0, max_price=5000.0),
            TradingActivityFilter(min_history_days=20),
            PreMarketFilter(min_premarket_vol_pct=0.10, min_gap_pct=1.0),
            MarketRegimeFilter(max_vix=28.0),
        ]

    def scan(
        self,
        stocks: List[StockMetricsInput],
        context: Optional[MarketContextInput] = None,
        scan_timestamp: Optional[datetime] = None,
    ) -> List[ScannedCandidate]:
        """
        Execute screening pipeline on candidates.
        Returns deterministically ranked and sized ScannedCandidate list.
        """
        ts = scan_timestamp or datetime.min
        if not stocks:
            return []

        eligible_candidates: List[ScannedCandidate] = []
        rejected_candidates: List[ScannedCandidate] = []

        for stock in stocks:
            passed_all = True
            rejection_reason = "Passed all filters"

            for flt in self.filters:
                res = flt.evaluate(stock, context)
                if not res.passed:
                    passed_all = False
                    rejection_reason = f"[{flt.name}] {res.reason}"
                    break

            candidate = ScannedCandidate(
                symbol=stock.symbol.upper().strip(),
                instrument_id=stock.instrument_id,
                price=stock.price,
                avg_daily_turnover_cr=stock.avg_daily_turnover_cr,
                avg_daily_volume=stock.avg_daily_volume,
                atr_pct=stock.atr_20d_pct,
                gap_pct=stock.overnight_gap_pct,
                premarket_volume=stock.premarket_volume,
                premarket_volume_pct=stock.premarket_volume_pct,
                is_eligible=passed_all,
                status_reason=rejection_reason,
                rank=None,
                scan_timestamp=ts,
            )

            if passed_all:
                eligible_candidates.append(candidate)
            else:
                rejected_candidates.append(candidate)

        # Deterministic Ranking for Eligible Candidates:
        # Prioritizes Turnover (liquidity), Pre-market Volume Surge, and Gap Momentum
        def ranking_score(c: ScannedCandidate) -> float:
            return (
                c.avg_daily_turnover_cr * 1.0
                + (c.premarket_volume_pct * 1000.0)
                + (abs(c.gap_pct) * 50.0)
            )

        # Sort descending by score; secondary tiebreaker alphabetical symbol
        eligible_candidates.sort(key=lambda c: (-ranking_score(c), c.symbol))

        # Assign ranks
        ranked_candidates: List[ScannedCandidate] = []
        for rank_idx, cand in enumerate(eligible_candidates, start=1):
            ranked_candidates.append(
                ScannedCandidate(
                    symbol=cand.symbol,
                    instrument_id=cand.instrument_id,
                    price=cand.price,
                    avg_daily_turnover_cr=cand.avg_daily_turnover_cr,
                    avg_daily_volume=cand.avg_daily_volume,
                    atr_pct=cand.atr_pct,
                    gap_pct=cand.gap_pct,
                    premarket_volume=cand.premarket_volume,
                    premarket_volume_pct=cand.premarket_volume_pct,
                    is_eligible=True,
                    status_reason=cand.status_reason,
                    rank=rank_idx,
                    scan_timestamp=cand.scan_timestamp,
                    metadata={"ranking_score": round(ranking_score(cand), 2)},
                )
            )

        # Cap output to max_candidates
        selected_candidates = ranked_candidates[: self.max_candidates]
        return selected_candidates
