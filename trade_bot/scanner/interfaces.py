"""
Stock Scanner and Screening Interfaces.

Defines contracts for screening, filtering, and dynamic universe selection.
Decouples filtering logic from data acquisition infrastructure.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional, Protocol, runtime_checkable
from trade_bot.domain.models import Instrument
from trade_bot.scanner.models import (
    FilterResult,
    MarketContextInput,
    ScannedCandidate,
    StockMetricsInput,
)


@runtime_checkable
class IUniverseProvider(Protocol):
    """Contract for obtaining point-in-time tradable equity universes (e.g. NSE F&O)."""

    def get_fno_universe(self, scan_date: date) -> List[str]:
        """Return list of eligible F&O stock symbols active on scan_date."""
        ...


@runtime_checkable
class IScannerFilter(Protocol):
    """Protocol for a single screening filter criterion."""

    @property
    def name(self) -> str:
        """Name of the filter rule."""
        ...

    def evaluate(
        self,
        stock: StockMetricsInput,
        context: Optional[MarketContextInput] = None,
    ) -> FilterResult:
        """Evaluate if an instrument passes this filter."""
        ...


@runtime_checkable
class ICandidateScanner(Protocol):
    """Contract for scanning, filtering, and ranking candidate instruments."""

    def scan(
        self,
        stocks: List[StockMetricsInput],
        context: MarketContextInput,
        scan_timestamp: datetime,
    ) -> List[ScannedCandidate]:
        """Filter universe and return qualifying candidates ranked deterministically."""
        ...


@runtime_checkable
class IMarketDataProvider(Protocol):
    """Contract for acquiring metrics and market context required by the scanner."""

    def get_stock_metrics(
        self,
        symbols: List[str],
        scan_date: date,
    ) -> List[StockMetricsInput]:
        """Retrieve pre-computed daily metrics for candidates."""
        ...

    def get_market_context(self, scan_timestamp: datetime) -> MarketContextInput:
        """Retrieve benchmark index and VIX status for the scan timestamp."""
        ...
