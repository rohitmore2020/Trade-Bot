"""
Stock Scanner and Screening Interfaces.

Defines contracts for screening, filtering, and dynamic universe selection.
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable
from trade_bot.domain.models import Instrument


@runtime_checkable
class IScannerFilter(Protocol):
    """Protocol for a single screening filter criterion."""

    @property
    def name(self) -> str:
        """Name of the filter rule."""
        ...

    def evaluate(self, instrument: Instrument) -> bool:
        """Evaluate if an instrument passes this filter."""
        ...


@runtime_checkable
class IStockScanner(Protocol):
    """Protocol for scanning and ranking candidate instruments."""

    def scan(self, universe: List[Instrument]) -> List[Instrument]:
        """Filter universe and return qualifying candidates ranked by score."""
        ...
