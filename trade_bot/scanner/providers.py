"""
Universe Providers for Dynamic Stock Scanner.

Supplies point-in-time tradable equity universes to eliminate survivorship bias.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Set
from trade_bot.data.universe_history import CORE_FNO_EQUITIES, HistoricalUniverseRegistry
from trade_bot.scanner.interfaces import IUniverseProvider


class StaticUniverseProvider:
    """Universe provider returning a fixed list of symbols."""

    def __init__(self, symbols: Optional[List[str]] = None) -> None:
        self.symbols = sorted(list(symbols or CORE_FNO_EQUITIES))

    def get_fno_universe(self, scan_date: date) -> List[str]:
        return list(self.symbols)


class HistoricalUniverseProvider:
    """
    Point-in-time universe provider backed by HistoricalUniverseRegistry.
    Eliminates survivorship bias by honoring historical additions/exclusions.
    """

    def __init__(self, registry: Optional[HistoricalUniverseRegistry] = None) -> None:
        self.registry = registry or HistoricalUniverseRegistry()

    def get_fno_universe(self, scan_date: date) -> List[str]:
        return self.registry.get_fno_universe_on_date(scan_date)
