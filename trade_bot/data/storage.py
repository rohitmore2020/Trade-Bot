"""
Parquet Columnar Candle Storage Repository.

High-performance local storage for historical OHLCV data using Apache Parquet.
Partitions data by timeframe and symbol with strict schema validation.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional
import pandas as pd
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.data.interfaces import ICandleStorage
from trade_bot.data.normalization import (
    dataframe_to_candles,
    normalize_ohlcv_dataframe,
)
from trade_bot.domain.models import Candle


class ParquetCandleStorage(ICandleStorage):
    """
    Columnar storage engine writing partitioned Parquet datasets to local disk.
    Directory structure:
        {base_dir}/{timeframe_seconds}s/{symbol}.parquet
    """

    def __init__(self, base_dir: str | Path = "data/historical") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, symbol: str, timeframe_seconds: int) -> Path:
        tf_dir = self.base_dir / f"{timeframe_seconds}s"
        tf_dir.mkdir(parents=True, exist_ok=True)
        return tf_dir / f"{symbol.upper().strip()}.parquet"

    def store_candles(
        self,
        candles: List[Candle] | pd.DataFrame,
        symbol: str,
        timeframe_seconds: int = 300,
    ) -> int:
        """
        Append or overwrite normalized candles into Parquet storage.
        Deduplicates on timestamp and preserves chronological sorting.
        """
        if isinstance(candles, pd.DataFrame):
            new_df = normalize_ohlcv_dataframe(candles, symbol=symbol)
        else:
            records = [
                {
                    "timestamp": c.timestamp,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "symbol": c.symbol,
                }
                for c in candles
            ]
            new_df = normalize_ohlcv_dataframe(pd.DataFrame(records), symbol=symbol)

        if new_df.empty:
            return 0

        target_file = self._get_file_path(symbol, timeframe_seconds)
        if target_file.exists():
            existing_df = pd.read_parquet(target_file)
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            # Re-normalize and deduplicate
            final_df = normalize_ohlcv_dataframe(combined_df, symbol=symbol)
        else:
            final_df = new_df

        # Save to Parquet with snappy compression
        final_df.to_parquet(target_file, index=False, engine="pyarrow", compression="snappy")
        return len(final_df)

    def load_dataframe(
        self,
        symbol: str,
        timeframe_seconds: int = 300,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Query local Parquet file and return filtered pandas DataFrame."""
        target_file = self._get_file_path(symbol, timeframe_seconds)
        if not target_file.exists():
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol"])

        df = pd.read_parquet(target_file)
        if df.empty:
            return df

        # Ensure tz-aware Asia/Kolkata
        if df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert(IST_TIMEZONE)
        else:
            df["timestamp"] = df["timestamp"].dt.tz_convert(IST_TIMEZONE)

        if start_time is not None:
            st = start_time if start_time.tzinfo else start_time.replace(tzinfo=IST_TIMEZONE)
            df = df[df["timestamp"] >= st]

        if end_time is not None:
            et = end_time if end_time.tzinfo else end_time.replace(tzinfo=IST_TIMEZONE)
            df = df[df["timestamp"] <= et]

        return df.sort_values(by="timestamp").reset_index(drop=True)

    def load_candles(
        self,
        symbol: str,
        timeframe_seconds: int = 300,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Candle]:
        """Query local Parquet file and return filtered list of domain Candle instances."""
        df = self.load_dataframe(symbol, timeframe_seconds, start_time, end_time)
        return dataframe_to_candles(df, timeframe_seconds=timeframe_seconds)

    def list_stored_symbols(self, timeframe_seconds: int = 300) -> List[str]:
        """List all symbols stored under this timeframe."""
        tf_dir = self.base_dir / f"{timeframe_seconds}s"
        if not tf_dir.exists():
            return []
        return sorted([f.stem for f in tf_dir.glob("*.parquet")])
