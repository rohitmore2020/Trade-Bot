"""
Historical Universe & F&O Membership Registry.

Maintains point-in-time NSE F&O constituent lists to eliminate survivorship bias during backtesting.
Tracks additions, removals, and regulatory surveillance actions.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Set


# Core persistent F&O symbols active throughout 2023-2026
CORE_FNO_EQUITIES: Set[str] = {
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "HCLTECH",
    "BAJFINANCE", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "TATAMOTORS",
    "WIPRO", "NTPC", "POWERGRID", "M&M", "TECHM", "BAJAJFINSV", "NESTLEIND",
    "GRASIM", "JSWSTEEL", "ADANIENT", "ADANIPORTS", "TATASTEEL", "COALINDIA",
    "BPCL", "BRITANNIA", "CIPLA", "EICHERMOT", "DIVISLAB", "DRREDDY", "APOLLOHOSP",
    "HEROMOTOCO", "INDUSINDBK", "TATACONSUM", "HINDALCO", "SBILIFE", "HDFCLIFE",
    "BAJAJ-AUTO", "UPL", "VEDL", "DLF", "GODREJCP", "PIDILITIND", "CHOLAFIN",
    "TRENT", "BEL", "HAL", "CANBK", "BANKBARODA", "SIEMENS", "PFC", "RECLTD"
}


class HistoricalUniverseRegistry:
    """
    Registry for point-in-time F&O universe lookup to eliminate survivorship bias.
    """

    def __init__(self) -> None:
        self._exclusions_by_date: Dict[date, Set[str]] = {}
        self._additions_by_date: Dict[date, Set[str]] = {}

    def register_exclusion(self, symbol: str, effective_date: date) -> None:
        """Register date when symbol was excluded from F&O."""
        self._exclusions_by_date.setdefault(effective_date, set()).add(symbol)

    def register_addition(self, symbol: str, effective_date: date) -> None:
        """Register date when symbol was admitted into F&O."""
        self._additions_by_date.setdefault(effective_date, set()).add(symbol)

    def is_fno_eligible_on_date(self, symbol: str, target_date: date) -> bool:
        """Check if symbol was an active F&O constituent on target_date."""
        sym = symbol.upper().strip()
        # Check if excluded prior to or on target_date
        for excl_date, syms in self._exclusions_by_date.items():
            if target_date >= excl_date and sym in syms:
                return False
        # Check if added on or prior to target_date
        for add_date, syms in self._additions_by_date.items():
            if target_date >= add_date and sym in syms:
                return True
        # Check if scheduled for addition after target_date
        for add_date, syms in self._additions_by_date.items():
            if target_date < add_date and sym in syms:
                return False
        return sym in CORE_FNO_EQUITIES

    def get_fno_universe_on_date(self, target_date: date) -> List[str]:
        """Return full list of eligible F&O symbols on target_date."""
        universe: Set[str] = set(CORE_FNO_EQUITIES)
        for add_date, syms in self._additions_by_date.items():
            if target_date >= add_date:
                universe.update(syms)
        for excl_date, syms in self._exclusions_by_date.items():
            if target_date >= excl_date:
                universe.difference_update(syms)
        return sorted(list(universe))
