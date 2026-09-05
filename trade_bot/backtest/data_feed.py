"""
Historical Market Data Feed for Backtesting.

Streams multi-asset historical candles chronologically without look-ahead leakage.
Supports in-memory Candle lists, Pandas DataFrames, and Parquet storage.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Dict, Iterator, List, Optional, Set, Tuple
import pandas as pd

from trade_bot.data.interfaces import ICandleStorage
from trade_bot.domain.models import Candle
from trade_bot.indicators.exceptions import LookAheadViolationError


class HistoricalDataFeed:
    """
    Deterministic chronological multi-asset historical candle feed.
    Guarantees strict zero look-ahead bias during bar streaming.
    """

    def __init__(
        self,
        candles_by_symbol: Optional[Dict[str, List[Candle]]] = None,
        dataframes_by_symbol: Optional[Dict[str, pd.DataFrame]] = None,
        candle_storage: Optional[ICandleStorage] = None,
        vix_data: Optional[Dict[datetime, float]] = None,
        timeframe_seconds: int = 300,
    ) -> None:
        self._raw_candles: Dict[str, List[Candle]] = defaultdict(list)
        self.timeframe_seconds = timeframe_seconds
        self.candle_storage = candle_storage
        self.vix_data: Dict[datetime, float] = vix_data or {}

        # Ingest pre-supplied Candle lists
        if candles_by_symbol:
            for sym, candles in candles_by_symbol.items():
                self._raw_candles[sym.upper().strip()].extend(candles)

        # Ingest pre-supplied DataFrames
        if dataframes_by_symbol:
            for sym, df in dataframes_by_symbol.items():
                self._ingest_dataframe(sym.upper().strip(), df)

        self._timeline: List[datetime] = []
        self._bars_by_timestamp: Dict[datetime, Dict[str, Candle]] = defaultdict(dict)
        self._previous_day_closes: Dict[str, Dict[date, float]] = defaultdict(dict)
        self._is_indexed: bool = False

    def _ingest_dataframe(self, symbol: str, df: pd.DataFrame) -> None:
        """Convert a standard OHLCV DataFrame into domain Candle objects."""
        if df.empty:
            return

        df_sorted = df.sort_values(by="timestamp")
        for _, row in df_sorted.iterrows():
            ts = row["timestamp"]
            if isinstance(ts, str):
                ts = pd.to_datetime(ts).to_pydatetime()
            elif isinstance(ts, pd.Timestamp):
                ts = ts.to_pydatetime()

            candle = Candle(
                symbol=symbol,
                timestamp=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                timeframe_seconds=self.timeframe_seconds,
                is_closed=True,
            )
            self._raw_candles[symbol].append(candle)

    def add_candles(self, symbol: str, candles: List[Candle]) -> None:
        """Add list of Candle models for a symbol."""
        self._raw_candles[symbol.upper().strip()].extend(candles)
        self._is_indexed = False

    def load_from_storage(
        self,
        symbols: List[str],
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> None:
        """Load candle data directly from local ICandleStorage."""
        if self.candle_storage is None:
            raise ValueError("No candle_storage repository was provided")

        for sym in symbols:
            loaded = self.candle_storage.load_candles(
                symbol=sym,
                timeframe_seconds=self.timeframe_seconds,
                start_time=start_time,
                end_time=end_time,
            )
            self.add_candles(sym, loaded)

    def index_data(self) -> None:
        """
        Organizes all loaded candles across instruments into a unified chronological timeline.
        Precomputes previous-session close for morning gap calculations without lookahead.
        """
        self._bars_by_timestamp.clear()
        self._previous_day_closes.clear()
        timestamps_set: Set[datetime] = set()

        for sym, candles in self._raw_candles.items():
            # Sort candles chronologically per symbol
            sorted_candles = sorted(candles, key=lambda c: c.timestamp)

            # Precompute session closing prices per date for gap tracking
            daily_candles: Dict[date, List[Candle]] = defaultdict(list)
            for c in sorted_candles:
                daily_candles[c.timestamp.date()].append(c)
                timestamps_set.add(c.timestamp)
                self._bars_by_timestamp[c.timestamp][sym] = c

            sorted_dates = sorted(daily_candles.keys())
            for i, d in enumerate(sorted_dates):
                if i > 0:
                    prev_date = sorted_dates[i - 1]
                    # The previous session close is the close of the last bar of the previous date
                    prev_close = daily_candles[prev_date][-1].close
                    self._previous_day_closes[sym][d] = prev_close

        self._timeline = sorted(list(timestamps_set))
        self._is_indexed = True

    def stream_bars(self) -> Iterator[Tuple[datetime, Dict[str, Candle]]]:
        """
        Yields (timestamp, {symbol: candle}) in strict monotonic chronological order.
        Guarantees that at bar t, no data from t+1 or later is accessible.
        """
        if not self._is_indexed:
            self.index_data()

        last_ts: Optional[datetime] = None
        for ts in self._timeline:
            if last_ts is not None and ts <= last_ts:
                raise LookAheadViolationError(
                    f"Chronological anomaly in feed timeline: timestamp {ts} <= last {last_ts}"
                )
            last_ts = ts
            # Yield shallow copy of bars for this timestamp
            yield ts, dict(self._bars_by_timestamp[ts])

    def get_vix_for_timestamp(self, ts: datetime) -> Optional[float]:
        """Look up VIX for timestamp or current date."""
        if ts in self.vix_data:
            return self.vix_data[ts]
        # Check by date
        date_ts = datetime(ts.year, ts.month, ts.day, tzinfo=ts.tzinfo)
        return self.vix_data.get(date_ts)

    def get_previous_session_close(self, symbol: str, session_date: date) -> Optional[float]:
        """Get the previous day's close for a symbol on session_date."""
        if not self._is_indexed:
            self.index_data()
        return self._previous_day_closes.get(symbol.upper().strip(), {}).get(session_date)

    def get_symbols(self) -> List[str]:
        return sorted(list(self._raw_candles.keys()))

    def get_total_bars(self) -> int:
        if not self._is_indexed:
            self.index_data()
        return len(self._timeline)
