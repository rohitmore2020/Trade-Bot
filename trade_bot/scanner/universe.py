"""
Watchlist and Universe Management.

Manages tradable equity universes (e.g. Nifty 50, Liquid Universe).
"""

from __future__ import annotations

from typing import Dict, List, Optional
from trade_bot.domain.enums import InstrumentType
from trade_bot.domain.models import Instrument


DEFAULT_NIFTY50_SYMBOLS = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "HINDUNILVR",
    "ITC",
    "SBIN",
    "BHARTIARTL",
    "KOTAKBANK",
    "LT",
    "AXISBANK",
    "ASIANPAINT",
    "HCLTECH",
    "BAJFINANCE",
    "MARUTI",
    "SUNPHARMA",
    "TITAN",
    "ULTRACEMCO",
    "TATAMOTORS",
]


class UniverseManager:
    """
    Registry and manager for trading universes and instruments.
    """

    def __init__(self) -> None:
        self._instruments: Dict[str, Instrument] = {}
        for sym in DEFAULT_NIFTY50_SYMBOLS:
            self.register_instrument(
                Instrument(
                    symbol=sym,
                    exchange="NSE",
                    segment="EQ",
                    instrument_type=InstrumentType.EQUITY,
                    lot_size=1,
                    tick_size=0.05,
                )
            )

    def register_instrument(self, instrument: Instrument) -> None:
        """Register an instrument in the universe."""
        self._instruments[instrument.symbol] = instrument

    def get_instrument(self, symbol: str) -> Optional[Instrument]:
        """Retrieve instrument by symbol."""
        return self._instruments.get(symbol)

    def get_all_symbols(self) -> List[str]:
        """Return list of all registered symbols."""
        return list(self._instruments.keys())

    def get_universe(self, symbols: Optional[List[str]] = None) -> List[Instrument]:
        """Return instruments matching the requested symbols, or all if None."""
        if symbols is None:
            return list(self._instruments.values())
        return [self._instruments[s] for s in symbols if s in self._instruments]
