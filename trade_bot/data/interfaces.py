"""
Market Data Interfaces and Abstractions.

Defines protocols for streaming tick providers, historical data loaders,
candle aggregators, local storage repositories, and data quality validators.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable
import pandas as pd
from trade_bot.domain.models import Candle, Tick


from trade_bot.data.events import ConnectionStatus, MarketDataEvent


@runtime_checkable
class IRealtimeMarketDataProvider(Protocol):
    """Protocol for real-time market data providers with connection and subscription management."""

    def connect(self) -> None:
        """Establish connection to data stream."""
        ...

    def disconnect(self) -> None:
        """Close connection to data stream."""
        ...

    def is_connected(self) -> bool:
        """Return True if connection is alive."""
        ...

    def get_connection_status(self) -> ConnectionStatus:
        """Return detailed connection lifecycle status."""
        ...

    def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to real-time quotes/ticks for given symbols."""
        ...

    def unsubscribe(self, symbols: List[str]) -> None:
        """Unsubscribe from real-time quotes/ticks."""
        ...

    def get_subscriptions(self) -> set[str]:
        """Return set of currently subscribed symbols."""
        ...

    def register_event_listener(self, listener: Callable[[MarketDataEvent], None]) -> None:
        """Register callback for normalized market data events."""
        ...

    def register_tick_handler(self, handler: Callable[[Tick], None]) -> None:
        """Register callback for incoming ticks."""
        ...


# Aliases for architectural requirements
RealtimeMarketDataProvider = IRealtimeMarketDataProvider
IMarketDataProvider = IRealtimeMarketDataProvider


@runtime_checkable
class IHistoricalDataLoader(Protocol):
    """Protocol for fetching historical candle data."""

    def load_candles(
        self,
        symbol: str,
        timeframe_seconds: int,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Candle]:
        """Load historical candles for a symbol within time range."""
        ...


@runtime_checkable
class IHistoricalDataProvider(Protocol):
    """Protocol for downloading and querying historical market data from external APIs."""

    @property
    def source_name(self) -> str:
        """Identifier for the data vendor/provider."""
        ...

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe_seconds: int,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data as a standardized pandas DataFrame.
        Columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'symbol']
        """
        ...


HistoricalMarketDataProvider = IHistoricalDataProvider


@runtime_checkable
class ICandleStorage(Protocol):
    """Protocol for persisting and retrieving normalized historical candle datasets."""

    def store_candles(self, candles: List[Candle] | pd.DataFrame, symbol: str, timeframe_seconds: int) -> int:
        """Persist candles to local storage. Returns count of rows written."""
        ...

    def load_candles(
        self,
        symbol: str,
        timeframe_seconds: int,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Candle]:
        """Load normalized candles as domain models."""
        ...

    def load_dataframe(
        self,
        symbol: str,
        timeframe_seconds: int,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Load normalized candles directly as a pandas DataFrame."""
        ...

    def list_stored_symbols(self, timeframe_seconds: int) -> List[str]:
        """Return all symbols available in local storage for a given timeframe."""
        ...


@runtime_checkable
class ICandleAggregator(Protocol):
    """Protocol for aggregating streaming ticks into OHLCV candles."""

    def process_tick(self, tick: Tick) -> Optional[Candle]:
        """
        Process a single tick. Returns closed Candle if a candle boundary was crossed, else None.
        """
        ...

    def get_current_candle(self, symbol: str) -> Optional[Candle]:
        """Return the unclosed (forming) candle for a symbol."""
        ...

    def register_candle_handler(self, handler: Callable[[Candle], None]) -> None:
        """Register callback for when a new candle closes."""
        ...
